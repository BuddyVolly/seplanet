import json
import time
from datetime import datetime as dt

import planet
from planet import api
import backoff 


import planetpy.helpers.tools as t
    
    
def build_order(aoi, inventory_gdf, title, tools, out_projection, anchor_image_id, ee_project=None, ee_collection=None):
    
    #------------------------------------------
    # 1 create toolchain
    
    # subset inventory to co-registration
    tools = t.create_toolchain(tools, aoi, inventory_gdf, anchor_image_id)
    #------------------------------------------
    
    if out_projection != 'EPSG:4326':
        tools.append({
            "reproject": {
                "projection": out_projection,
                "kernel": "cubic"
            }
        })
    #------------------------------------------
    # 2 create products_order
    products_bundles = {

        # Is not possible to ask for analytic_dn in PSScene3Band, so the next option is visual
        # for more info go to https://developers.planet.com/docs/orders/product-bundles-reference/
        'PSScene3Band': "analytic",
        'PSScene4Band': "analytic_udm2",
        'PSOrthoTile': "analytic_5b_udm2,analytic_5b,analytic_udm2,analytic",
        'REOrthoTile': "analytic",
        'SkySatScene': "analytic_udm2",
    }

    # This will create a tuple with the item_type and with the corresponding associated item_ids'
    items_by_type = [
        (item_type, inventory_gdf[inventory_gdf.item_type == item_type].id.to_list())
        for item_type in inventory_gdf.item_type.unique()
    ]

    # create product order
    products_order = [
        {
            "item_type":k, 
            "item_ids":v, 
            "product_bundle": products_bundles[k]
        } for k, v in items_by_type
    ]
    #------------------------------------------
    
    #------------------------------------------
    # 3 get order request together
    order_request = {
        'name': str(title),
        "order_type":"partial",
        'products': products_order,
        'tools': tools
    }
    #------------------------------------------
    
    #------------------------------------------
    # 4 add gee delivery if project and collection are provided
    if ee_project and ee_collection:
        
        
        # update order request dict
        order_request.update(
           delivery={
               'google_earth_engine': {
            'project': ee_project,
            'collection': ee_collection
            }
           }
         ) 
    #------------------------------------------
    
    return order_request


def get_existing_orders(client, pages=1):
    # Search all the requested orders per page
    # Fixed api.models NEXT_KEY parameter from "_next" to "next"

    ordered_orders = client.get_orders()
    ordered_orders.NEXT_KEY = "next"
    order_pages=[]

    # We can limit the search to certain number of pages
    # if we leave as none, will search over all of them
    limit_to_x_pages = pages
    for page in ordered_orders.iter(limit_to_x_pages):
        page.NEXT_KEY = "next"
        order_pages.append(page.get())

    current_server_orders = [order for page in order_pages for order in page['orders']]
    
    return current_server_orders



def place_order(client, order_request, log_dir, resubmit=False):
    
    order_title = order_request['name']
    
    # check first if we already have an order of that name
    current_orders = get_existing_orders(client, None)
    orders_names = [order['name'] for order in current_orders]
    
    try:
        order = [order for order in current_orders if order_title == order['name']][0]
    except:
        order = {'state': 'no order yet'}
     
    if not resubmit:
        if order_title in orders_names and order['state'] in ['success', 'partial']:
            raise Exception(
                'Successful order has been already placed. '
                'Set resubmit option to True in case you want to re-order the images.')

    now = dt.now().strftime('%Y%m%d_%H_%M')
    log = log_dir.joinpath(f'order_log_{order_title}_{now}')
    
    try:
        # The following line will create the order in the server
        @backoff.on_exception(backoff.expo,planet.api.exceptions.OverQuota, max_time=360)
        def _place_order(_order_request):
            return client.create_order(_order_request).get()

        order_info = _place_order(order_request)
        
        order_id = order_info['id']
        order_name = order_info['name']

        print(f'Order {order_id} with {order_name} has been placed.')
            
    except Exception as e:
        with open(log, 'a') as lf:
            print(
                f'There was an error with the order {order_title}. '
                f'Please check the log file at {str(log)}.'
            )
            lf.write(f'Order {order_title}: {e}\n')
            
            
def download_order(client, order_title, download_dir, log_dir):

    current_orders = get_existing_orders(client, None)
    order = [order for order in current_orders if order_title == order['name']][0]
    
    while order['state'] not in ['success', 'partial']:
        current_orders = get_existing_orders(client, None)
        order = [
            order for order in current_orders if order_title == order['name']
        ][0]
        print('Scenes not yet available, will wait another 30 seconds.')
        time.sleep(30)
    
    now = dt.now().strftime('%Y%m%d_%H_%M')
    log = log_dir.joinpath(f'download_log_{order_title}_{now}')
    
    try:
        callback = api.write_to_file(directory=str(download_dir), overwrite=True)
        
        @backoff.on_exception(backoff.expo,planet.api.exceptions.OverQuota,max_time=360)
        def download(_order):
            print('Downloading')
            client.download_order(_order, callback=callback)

        download(order['id'])
        
    except Exception as e:
        print(
            f'There was an error with the download for {order_title}. '
            f'please check the log file at {str(log)}.'
        )
        with open(log, 'w') as lf:
            lf.write(f'Order {order_title}:{e}\n')
