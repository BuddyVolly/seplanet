def get_ee_collection_names(ee_project, ee_collection):
    """Planet Google delivery just needs the stem, while ee API for generation needs the full path
    
    
    """
    
    if ee_collection.startswith('projects/'):
        ee_order_collection = '/'.join(ee_collection.split('/')[3:])
    else:
        ee_order_collection = ee_collection
        ee_collection = f'projects/{ee_project}/assets/{ee_collection}'

    return ee_order_collection, ee_collection
    

def create_image_collection(image_collection):
    
        # get actual asset name (and folder)
        coll_path_list = image_collection.split('/')[3:]
        
        # check if image collection is there, otherwise create it
        try:
            import ee
            ee.Initialize()
            
            # create folder, if there
            if len(coll_path_list) == 2:
                ee.data.createAsset({'type':'FOLDER'}, '/'.join(image_collection.split('/')[:4]))
            
            # create collection
            ee.data.createAsset({'type':'IMAGE_COLLECTION'}, image_collection)
        
        except Exception as e:
        
            if str(e).startswith('Cannot overwrite asset'):
                print('NOTE: Will add images to already exisiting Earthengine image collection.')
                pass
            else:
                raise Exception(e)