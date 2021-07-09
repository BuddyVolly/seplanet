import json

import numpy as np
from shapely.geometry import shape

def create_toolchain(tools, aoi=None, inventory_gdf=None, anchor_image_id=None):
 
    # toolchain art for adding ndvi to a 4 band image
    ndvi = {
          "bandmath": {
            "b1": "b1",
            "b2": "b2",
            "b3": "b3",
            "b4": "b4",
            "b5": "(b4-b3)/(b4+b3)",
            "pixel_type": "32R"
          }
        }
    
    
    # toolchain for ndvi only
    ndvi_only = {
      "bandmath": {
        "pixel_type": "32R",
        "b1": "(b4 - b3) / (b4 + b3)"
      }
    }
    
    # composite
    composite = {
          "composite": {
            }
        }

    def co_register(anchor_image):
        return {
          "coregister": {
            "anchor_item": anchor_image
          }
        }

    def clip(aoi):
        return {
            'clip': {
                'aoi': json.loads(aoi.geometry.to_json())['features'][0]['geometry']
            }
        }
    
    
    # here we fill the toolchain list that we return
    toolchain = []
    if 'co-register' in tools:
        # we need some 
        toolchain.append(co_register(anchor_image_id))
        
    if 'add_NDVI' in tools:
        toolchain.append(ndvi)
        
    if 'NDVI_only' in tools:
        toolchain.append(ndvi_only)

    if 'clip' in tools:
        toolchain.append(clip(aoi))

    return toolchain


def select_anchor_image(inventory_gdf):

    # consider images with least cloud cover (within the 10th percentile)
    subset_gdf = inventory_gdf[inventory_gdf.cloud_cover <= np.percentile(inventory_gdf.cloud_cover, 10)]
    
    # now we select the image with best overlap with respectot the rest
    final_sum = 0
    for i in range(len(subset_gdf)):

        geom = shape(subset_gdf.iloc[i].geometry)
        _sum = inventory_gdf.apply(lambda row: row.geometry.intersection(geom).area / geom.area, axis=1).sum()
        if _sum > final_sum:
            final_sum = _sum
            anchor_image_id = subset_gdf.iloc[i].id
    
    return anchor_image_id


def filter_coregistered_inventory(inventory_gdf, overlap_threshold=50):
    
    # get best anchor image
    anchor_image_id = select_anchor_image(inventory_gdf)
    
    # get anchor image geometry 
    anchor_image_geom = shape(inventory_gdf[inventory_gdf.id == anchor_image_id].geometry.values[0])
    
    # calculate overlap to each image
    inventory_gdf['anchor_overlap'] = inventory_gdf.apply(
        lambda row: 100*(row.geometry.intersection(anchor_image_geom).area / anchor_image_geom.area), axis=1
    )
    
    # return anchor image and filtered collection with minimum overlap
    return anchor_image_id, inventory_gdf[inventory_gdf.anchor_overlap >= overlap_threshold]