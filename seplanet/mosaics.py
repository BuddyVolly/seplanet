import time
import shutil
from pathlib import Path
from datetime import datetime as dt

import gdal
from planet import api

import seplanet.helpers.helpers as h
import seplanet.helpers.mosaics as m


class Mosaics():
    
    def __init__(
            self,
            project_name,
            project_dir,
            aoi,
            start_date='2016-01-01',
            end_date=dt.today().strftime('%Y-%m-%d'),
            nicfi_api_key='',
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
        
        # define project sub-directories if not set, and create folders
        self.processing_dir = self.project_dir.joinpath('process')
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        print(
            f'Processed data will be stored in: {self.processing_dir}.'
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
        
        # connector
        self.nicfi_api_key = nicfi_api_key
        
        
    def get_mosaics(self):

        # get necessary tiles to download
        self.tileslist = m.get_tiles(self.aoi, self.start_date, self.end_date, self.nicfi_api_key)

        # download tiles
        print(f'Have to download {len(self.tileslist)} tiles.')
        m.download_tiles(self.download_dir, self.tileslist)

    
    def create_ndvi_timeseries(self):
        
        for file in self.download_dir.glob('**/*.tif'):
            
            # create outfile name
            folder = self.processing_dir.joinpath('/'.join(str(file).split('/')[-3:-1]))
            folder.mkdir(parents=True, exist_ok=True)            
            outfile = folder.joinpath(f'{file.stem}.ndvi.tif')
       
            # calculate ndvi
            h.calculate_ndvi(file, outfile)
            
        # create stacks for ts analysis
        for tile in self.processing_dir.glob(f'0/tile*'):
            filelist = [str(file) for file in sorted(tile.glob('*ndvi.tif'))]
            datelist = [f'{file.name[:7]}-01' for file in sorted(tile.glob('*ndvi.tif'))]
            outfile = tile.joinpath('stack.vrt')
            opts = gdal.BuildVRTOptions(srcNodata=0, VRTNodata=0, separate=True)
            vrt = gdal.BuildVRT(str(outfile), filelist, options=opts)
            vrt.FlushCache()
            
            # add date description
            ds = gdal.Open(str(outfile), gdal.GA_Update)
            for idx, desc in enumerate(datelist):
                rb = ds.GetRasterBand(idx+1)
                rb.SetDescription(desc)
            del ds
            
        # copy dates file   
        dates_file = list(self.download_dir.glob('**/dates.csv'))[0]
        shutil.copy(dates_file, self.processing_dir.joinpath('0/dates.csv'))
