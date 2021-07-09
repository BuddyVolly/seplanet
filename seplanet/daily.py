import time
from pathlib import Path
from datetime import datetime as dt

from planet import api

import seplanet.helpers.helpers as h
import seplanet.helpers.inventory as i
import seplanet.helpers.orders as o
import seplanet.helpers.earthengine as ee
import seplanet.helpers.tools as t


class Daily():
    
    def __init__(
            self,
            project_name,
            project_dir,
            aoi,
            start_date='2008-01-01',
            end_date=dt.today().strftime('%Y-%m-%d'),
            max_cloud_cover=95,
            planet_api_key='',
            constellations=[
                        'PSScene4Band', 'PSScene3Band','PSOrthoTile','REOrthoTile', 'SkySatScene'
                       ],
            out_projection='EPSG:4326'
            
    ):
        
        
        # the name of the project
        self.project_name = project_name
        
        # get absolute path to project directory
        self.project_dir = Path(project_dir).resolve()

        # create project directory if not existent
        try:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            print(f'Created project directory at {self.project_dir}')
        except FileExistsError:
            print('Project directory already exists. '
                  'No data has been deleted at this point but '
                  'make sure you really want to use this folder.'
            )

        # define project sub-directories if not set, and create folders
        self.download_dir = self.project_dir.joinpath('download')
        self.download_dir.mkdir(parents=True, exist_ok=True)
        print(
            f'Downloaded data will be stored in: {self.download_dir}.'
        )

        self.inventory_dir = self.project_dir.joinpath('inventory')
        self.inventory_dir.mkdir(parents=True, exist_ok=True)
        print(
            f'Inventory files will be stored in: {self.inventory_dir}.'
        )
        
        self.log_dir = self.project_dir.joinpath('log')
        self.log_dir.mkdir(parents=True, exist_ok=True)
        print(
            f'Log files will be stored in: {self.log_dir}.'
        )

        # ------------------------------------------
        # 4 handle AOI (read and get back GeoDataFrame)
        self.aoi = h.aoi_to_gdf(aoi)
        
        # start and end date
        self.start_date = dt.strptime(start_date, '%Y-%m-%d')
        self.end_date = dt.strptime(end_date, '%Y-%m-%d')
        self.max_cloud_cover = max_cloud_cover
        
        # connector
        self.client = api.ClientV1(api_key=planet_api_key)
        
        # satellites
        self.constellations = constellations
        
        # gee delivery
        self.ee_cloud_project = None
        self.ee_image_collection = None
        
        # intialize tools
        self.tools = []
        # and standard projection
        self.out_projection = out_projection
        
        # an empty order request dictionary that we fill later
        self.order_request = {}
        
    def create_inventory(self):

        self.full_inventory = i.create_inventory(
            self.aoi, 
            self.start_date, 
            self.end_date, 
            self.max_cloud_cover, 
            self.constellations,
            self.client
        )
        
        # save full. inventory
        self.full_inventory.to_file(self.inventory_dir.joinpath('full_inventory.gpkg'), driver='GPKG')
        
    
    def refine_inventory(
            self, 
            max_cloud_cover=100, 
            scene_overlap=0, 
            aoi_overlap=0, 
            score=0, 
            every=None
    ):
        
        self.refined_inventory = i.refine_inventory(
            self.full_inventory, 
            max_cloud_cover, 
            scene_overlap,
            aoi_overlap, 
            score,            
            every
        )
    
        self.refined_inventory.to_file(self.inventory_dir.joinpath('refined_inventory.gpkg'), driver='GPKG')
    
    def plot_inventory(self, inventory_gdf, transparency=.1):
        i.plot_inventory(self.aoi, inventory_gdf, transparency)
        
        
    def create_order(self, inventory_gdf, resubmit=False, ask=True):
        
        #-------------------------------------
        # 1 check on EE image collection and create if not there yet
        pla_coll = None
        if self.ee_cloud_project and self.ee_image_collection:
            # catch collection names in form that planet and EE api wants it
            pla_coll, ee_coll = ee.get_ee_collection_names(
                self.ee_cloud_project, self.ee_image_collection
            )
            # create the image collection if not yet there
            ee.create_image_collection(ee_coll)
            
            # reset projection to make delivery work
            self.out_projection = 'EPSG:4326'
            
            # !check on tools (only clip allowed)!
        #-------------------------------------
        
        #-------------------------------------
        # check on competability of tools
        if 'co-register' in self.tools and 'composite' in self.tools:
            raise Exception(' Co-registration and composite are exclusive tools. Choose one or the other.')
            
        #-------------------------------------
        #-------------------------------------
        # 2 refine invetory for co-registration (if so)
        anchor_image_id = None
        if 'co-register' in self.tools:
            print(' INFO: Further refining inventory for co-registration success.')
            anchor_image_id, inventory_gdf = t.filter_coregistered_inventory(inventory_gdf)
        #-------------------------------------

        #-------------------------------------
        if 'composite' in self.tools:
            self.composite_inventory = o.create_composite_gdf(self.aoi, self.inventory_gdf)
            
            
        #-------------------------------------
        # 3 create order request(s)
        
        # save copy of ordered inventory
        inventory_gdf.to_file(self.inventory_dir.joinpath('ordered_inventory.gpkg'), driver='GPKG')
        
        # get number of images
        nr_images = len(inventory_gdf)
        
        if nr_images > 500 and 'co-register' in self.tools:
            raise Exception(' Co-register tool is not practicable for orders of more than 500 images.')
            
        # if order has more than 500 items we split to avoid hitting the limitation
        # therefore we loop over 500 rows 
        every = 500
        for idx, row in enumerate(range(0, nr_images, every)):

            # create order title
            order_title = f'{self.project_name}_{idx}' if nr_images > every else self.project_name
            
            # create the order
            self.order_request[order_title] = o.build_order(
                self.aoi, 
                inventory_gdf.iloc[row:row+every-1], 
                order_title, 
                self.tools,
                self.out_projection,
                anchor_image_id,
                self.ee_cloud_project, 
                pla_coll
            )
        #-------------------------------------
        
        #-------------------------------------
        # 4 Confirmation of order
        # as the next step will affect the quota, we ask for confirmation
        if ask: 
            print(
                f'NOTE: You are going to order {nr_images} images that will be '
                'subtracted from your quota. '
            ) 

            if len(self.order_request.keys()) > 1:
                print(
                    f'NOTE: To avoid running into limitations, the order is divided into '
                    f'{len(self.order_request.keys())} separated order requests.'
                )
            if input('Are you sure you want to place the order? (y/n)') != "y":
                return
        
        #-------------------------------------
        
        #-------------------------------------
        # 5 Place order request(s)
        # place each order request
        for idx, order in enumerate(self.order_request.keys()):
            print(f' Placing order {idx+1}/{len(self.order_request.keys())}')
            o.place_order(
                self.client, self.order_request[order], self.log_dir, resubmit
            )
        #-------------------------------------
        
        
    def download_order(self):
        
        for order in self.order_request.keys():
            o.download_order(self.client, order, self.download_dir, self.log_dir)
        
        
    def get_order_status(self, every_seconds=15):
        
        
        to_process = 999
        while to_process > 0:
    
            states, titles = [], []
            for title in self.order_request.keys():
                
                current_orders = o.get_existing_orders(self.client, pages=100)
                order = [
                    order for order in current_orders if title == order['name']
                ][0]
                print('Order: ' + title)
                print('Last message: ' + order['last_message'])
                states.append(order['state'])
                titles.append(title)
            if order['state'] not in ['success', 'partial', 'failed']:
                time.sleep(15)
        
            
            to_process = len(
                [state for state in states if state not in ['success', 'partial', 'failed']]
            )
            
        
        return [order for order in current_orders if order['name'] in titles]