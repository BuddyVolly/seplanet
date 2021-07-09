import backoff
import planet
from planet.api import filters

import pandas as pd
import geopandas as gpd
from shapely.geometry import shape

import planetpy.helpers.helpers as h

def build_request(
    aoi, 
    start_date, 
    end_date,
    max_cloud_cover, 
    constellations=[
        'PSScene4Band', 'PSScene3Band','PSOrthoTile','REOrthoTile', 'SkySatScene'
    ]
):
    """ Function to build a search request

    """

    # get aoi geometry
    search_aoi = h.aoi_to_geom_dict(aoi)
    
    # create query filter
    query = filters.and_filter(
        filters.geom_filter(search_aoi),
        filters.range_filter('cloud_cover', lt=max_cloud_cover),
        filters.date_range('acquired', gte=start_date),
        filters.date_range('acquired', lt=end_date)
    )

    # build a request 
    request = filters.build_search_request(
        query, item_types=constellations
    )
    
    return request


@backoff.on_exception(backoff.expo, planet.api.exceptions.OverQuota, max_time=360)
def get_items(request, client):
    """ Get items using the request with the given parameters
           
    """
    
    # query results 
    result = client.quick_search(request)
    
    # get result pages
    items_pages = [page.get() for page in result.iter(None)]
    
    # get each single item
    return [item for page in items_pages for item in page['features']]
    

def items_to_gdf(items):
    
    
    items_metadata = [
        (
            f['properties']['acquired'],
            f['id'], 
            f['properties']['item_type'],
            f['_links']['thumbnail'],
            str(f['_permissions']),
            f['geometry'],
            f['properties']['cloud_cover'],
            f
        ) for f in items
    ]
    
    
    # Store into dataframe
    df = pd.DataFrame(items_metadata)
    df[0] = pd.to_datetime(df[0])
    df.columns=[
        'timestamp', 
        'id', 
        'item_type', 
        'thumbnail', 
        'permissions', 
        'footprint', 
        'cloud_cover', 
        'metadata'
    ]
    
    df.sort_values(by=['timestamp'], inplace=True)
    df.reset_index()
    
    # get cloud cover as percentage
    df.cloud_cover = df.cloud_cover*100
    
    # add date only (without time)
    df['date'] = df.apply(lambda row: row['timestamp'].strftime('%Y-%m-%d'), axis=1)
    df['dove'] = df.apply(lambda row: row.id[16:], axis=1)
    
    # transform to geopandas
    return gpd.GeoDataFrame(
        df, geometry=df.apply(lambda row: shape(row['footprint']), axis=1)
    )
        
    
def add_overlaps(gdf, aoi):
    
    def get_overlap(geom):
        
        item_shape = shape(geom)
        scene_overlap = 100.0*(aoi_shape.intersection(item_shape).area / item_shape.area)
        aoi_overlap = 100.0*(aoi_shape.intersection(item_shape).area / aoi.area)
        return scene_overlap, aoi_overlap
    
    # get aoi geom
    aoi_shape = shape(h.aoi_to_geom_dict(aoi))
    
    # add overlap for each scene
    gdf['scene_overlap'], gdf['aoi_overlap'] = zip(*gdf.apply(lambda row: get_overlap(row['geometry']), axis=1))
    
    # extrat 2nd value that comes as tuple
    gdf['aoi_overlap'] = gdf['aoi_overlap'].apply(lambda row: row[0])
    return gdf
   

def add_score(gdf):
    """Filter and score each item according to the season and item_type
    
    Return:
        Scored items dataframe.
        
    """
    
    def get_score(row):
        #print(row)
        # item_type_score
        ITEM_TYPE_SCORE = {
            'PSScene4Band':9, 
            'PSScene3Band':7, 
            'PSOrthoTile':8,
            'REOrthoTile':0,
            'SkySatScene':0,
        }

        # season score
        MONTHS_SCORE = {
            1: 10, 7:10,
            2: 10, 8:10,
            3: 10, 9:10,
            4: 10, 10:10,
            5: 10, 11:10,
            6: 10, 12:10,
        }

        def cloud_score(cloud_cover):
            """ Define the cloud cover threshold and score

            1 = 1%

            """
           
            if cloud_cover == 0:
                return 10
            elif cloud_cover <= 1 and cloud_cover > 0:
                return 5
            else:
                return 0

        def cover_score(covered_area):
            """Define the cover area threshold and score
            """
            
            if covered_area >= 99:
                return 10

            elif covered_area >= 95:
                return 5

            else:
                return 0
    
        month = row['timestamp'].month
        return MONTHS_SCORE[month] + ITEM_TYPE_SCORE[row['item_type']] + cloud_score(row['cloud_cover']) + cover_score(row['scene_overlap'])
    
    gdf['total_score'] = gdf.apply(lambda row: get_score(row), axis=1)
    gdf.sort_values(by=['total_score', 'timestamp'], ascending=False)
    return gdf


def create_inventory(aoi, start_date, end_date, max_cloud_cover, constellations, client):
    
    # create request
    request = build_request(
            aoi,  
            start_date, 
            end_date,  
            max_cloud_cover, 
            constellations
        )
    
    # get items
    items = get_items(request, client)
    gdf = items_to_gdf(items)
        
    # add overlaps
    gdf = add_overlaps(gdf, aoi)
    
    # add score
    gdf = add_score(gdf)
        
    return gdf


def refine_inventory(full_gdf, cloud_cover=100, scene_overlap=0, aoi_overlap=0, score=0, every=None):
    
    gdf = full_gdf.copy()
    gdf = gdf[gdf['cloud_cover'] <= cloud_cover]
    gdf = gdf[gdf['scene_overlap'] >= scene_overlap]
    gdf = gdf[gdf['aoi_overlap'] >= aoi_overlap]
    gdf = gdf[gdf['total_score'] >= score]
    
    if every:
        
        # add column with only dates
        gdf['_date'] = pd.to_datetime(gdf.timestamp.dt.date)
        
        # sort values
        gdf = gdf.sort_values(
            by=['_date', 'total_score', 'aoi_overlap', 'cloud_cover'],
            ascending=[True, False, False, True]
        )
        # group them
        gdf = gdf.groupby(
            pd.Grouper(key='_date', freq=every)
        ).first().dropna().reset_index().drop(columns='_date')
    
    return gdf


def create_composite_inventory(aoi, inventory_gdf):

    df = inventory_gdf.copy()
    df['comb'] = df.date + df.dove

    # get aoi geom
    aoi_shape = shape(h.aoi_to_geom_dict(p.aoi))

    d = {}
    for idx in df.comb.unique():

        temp_df = df[df.comb == idx]
        date = temp_df.head(1).date.values[0]
        scenes = list(temp_df.id.values)
        geometry = temp_df.geometry.unary_union
        intersect = 100 * (shape(geometry).intersection(aoi_shape).area / aoi_shape.area)
        d[date] = {'scenes' :scenes, 'aoi_intersect': intersect, 'geometry': geometry}

    composite_df = pd.DataFrame.from_dict(d, orient='index')
    return gpd.GeoDataFrame(composite_df, geometry='geometry')


def plot_inventory(aoi, inventory_df, transparency=0.05):

    import matplotlib.pyplot as plt

    # load world borders for background
    world = gpd.read_file(gpd.datasets.get_path('naturalearth_lowres'))

    # do the import of aoi as gdf
    
    # get bounds of AOI
    bounds = inventory_df.geometry.bounds

    # get world map as base
    base = world.plot(color='lightgrey', edgecolor='white')

    # plot aoi
    aoi.plot(ax=base, color='None', edgecolor='black')

    # plot footprints
    inventory_df.plot(ax=base, alpha=transparency)

    # set bounds
    plt.xlim([bounds.minx.min()-0.1, bounds.maxx.max()+0.1])
    plt.ylim([bounds.miny.min()-0.1, bounds.maxy.max()+0.1])
    plt.grid(color='grey', linestyle='-', linewidth=0.2)
