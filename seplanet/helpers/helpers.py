import json

from shapely.ops import transform
from shapely.wkt import loads
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.errors import WKTReadingError
from fiona import collection
from fiona.crs import from_epsg

# make crs work
import os 
if 'GDAL_DATA' in list(os.environ.keys()): del os.environ['GDAL_DATA']
if 'PROJ_LIB' in list(os.environ.keys()): del os.environ['PROJ_LIB']
    
import rasterio as rio
from rasterio.crs import CRS
import geopandas as gpd


def wkt_to_gdf(wkt):
    """

    :param wkt:
    :return:
    """

    warnings.filterwarnings('ignore', r'syntax is deprecated', FutureWarning)

    # load wkt
    geometry = loads(wkt)

    # point wkt
    if geometry.geom_type == 'Point':
        data = {'id': ['1'], 'geometry': loads(wkt).buffer(0.05).envelope}
        gdf = gpd.GeoDataFrame(data)
    
    # polygon wkt
    elif geometry.geom_type == 'Polygon':
        data = {'id': ['1'], 'geometry': loads(wkt)}
        gdf = gpd.GeoDataFrame(
            data, crs={'init': 'epsg:4326',  'no_defs': True}
        )

    # geometry collection of single multiploygon
    elif (
            geometry.geom_type == 'GeometryCollection' and
            len(geometry) == 1 and 'MULTIPOLYGON' in str(geometry)
    ):

        data = {'id': ['1'], 'geometry': geometry}
        gdf = gpd.GeoDataFrame(
            data, crs={'init': 'epsg:4326',  'no_defs': True}
        )
        
        ids, feats = [], []
        for i, feat in enumerate(gdf.geometry.values[0]):
            ids.append(i)
            feats.append(feat)

        gdf = gpd.GeoDataFrame(
            {'id': ids, 'geometry': feats},
            geometry='geometry',
            crs=gdf.crs
        )
    
    # geometry collection of single polygon
    elif geometry.geom_type == 'GeometryCollection' and len(geometry) == 1:
        
        data = {'id': ['1'],
                'geometry': geometry}
        gdf = gpd.GeoDataFrame(
            data, crs={'init': 'epsg:4326',  'no_defs': True}
        )

    # everything else
    else:

        i, ids, geoms = 1, [], []
        for geom in geometry:
            ids.append(i)
            geoms.append(geom)
            i += 1

        gdf = gpd.GeoDataFrame(
            {'id': ids, 'geometry': geoms},
            crs={'init': 'epsg:4326',  'no_defs': True}
        )
    
    return gdf


def aoi_to_gdf(aoi):
    
    # geopandas readable file
    try: 
        gdf = gpd.read_file(aoi)
        print(len(gdf))
        
    except:
        pass
    
    # feature collection
    try:
        gdf = gpd.GeoDataFrame.from_features(aoi)
        print(len(gdf))
        
    except:
        pass
    
    # plain geometry dict
    try:
        fc = {'type': 'FeatureCollection',
               "features": [
                    {
                  "type": "Feature",
                  "properties": {},
                  "geometry": aoi['geometry']
                    }]
                }
        gdf = gpd.GeoDataFrame.from_features(fc)
        
    except:
        pass

    
    # wkt
    try:
        gdf = wkt_to_gdf(aoi)
    except:
        pass
    
    
    # check if  we managed ot load something
    try:
        gdf
    except NameError:
        raise Exception('No valid AOI definition provided.')

    # restrict on 1 geometry
    if len(gdf) > 1:
        raise Exception('Not more than one geometry allowed for the AOI.')
    
    ## asssure EPSG 4326 Lat/Lon
    try:
        gdf = gdf.geometry.to_crs('epsg:4326') 
    except:
        print('No EPSG given for AOI geometry, setting to default EPSG 4326.')
        gdf.crs = 'epsg:4326'

    return gdf

        
def aoi_to_geom_dict(aoi_gdf):
    
    return aoi_gdf.__geo_interface__['features'][0]['geometry']


def calculate_ndvi(infile, outfile):
    
    date = infile.stem[:7] + '-01'
    with rio.open(infile) as src:
        
        # read bands
        nir = src.read(4)
        red = src.read(3)
        
        # copy metadata
        outmeta = src.meta
        outmeta.update(count=1)
        outmeta.update(dtype='float32')
        outmeta.update(compress='lzw')
        outmeta.update(crs=CRS.from_epsg(3857))
        
        ndvi = (nir-red)/(nir+red).astype('float32')
        
        with rio.open(outfile, 'w', **outmeta) as dst:
            dst.write(ndvi, 1)
            dst.set_band_description(1, date)