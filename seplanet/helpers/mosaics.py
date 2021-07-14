import requests
import concurrent.futures
from datetime import datetime as dt

import numpy as np
import tqdm 
import gdal 


def get_tiles(aoi, start_date, end_date, nicfi_api_key):

    print(start_date, end_date)
    # create base url
    url = 'https://api.planet.com/basemaps/v1/mosaics?api_key=' + nicfi_api_key
    
    # get all mosaics
    mosaics = requests.get(url).json()['mosaics']

    # filter by date
    mosaics_date_filtered = [
        m for m in mosaics 
        if dt.strptime(m['first_acquired'][0:10], '%Y-%m-%d') >= start_date
        and dt.strptime(m['first_acquired'][0:10], '%Y-%m-%d') <= end_date
    ]
    
    # filter by aoi's bbox
    # get bbox
    lx, ly, ux, uy = aoi.bounds.values[0]

    # reformat json strings
    mosaics_filtered = [
        m['_links']['quads'].replace('{lx}',str(lx))
         .replace('{ly}',str(ly))
         .replace('{ux}',str(ux))
         .replace('{uy}',str(uy))
        for m in mosaics_date_filtered
    ] 
    
    # get tile urls and metadata
    tiles, mosiacs = [], True
    for mosaics in mosaics_filtered:
        while mosaics:
            next_fetch = requests.get(mosaics).json()
            tiles.extend(next_fetch['items'])
            try:
                mosaics = next_fetch['_links']['_next']
            except Exception as e:
                mosaics = False
    
    return tiles


def download_tiles(download_dir, tiles):
    
    
    args_list, dates = [], []
    for tile in tiles:

        # get link 
        link = tile['_links']['download']

        # get metadate for filename creation
        tilename = tile['id']
        start = tile['_links']['thumbnail'].split('/')[6].split('_')[4]
        end = tile['_links']['thumbnail'].split('/')[6].split('_')[5]

        
        # download dest
        download_folder = download_dir.joinpath(f'0/tile_{tilename}')
        download_folder.mkdir(parents=True, exist_ok=True)
        download_dest = download_folder.joinpath(f'{start}_{end}_{tilename}.tif')

        args_list.append([link, download_dest])
        dates.append(start+'-01')        
    
    # parallel execution
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=8
        ) as executor:
            executor.map(download_tile, args_list)
    
    # create stacks for ts analysis
    for tile in download_dir.glob(f'0/tile*'):
        filelist = [str(file) for file in sorted(tile.glob('*tif'))]
        outfile = tile.joinpath('stack.vrt')
        opts = gdal.BuildVRTOptions(srcNodata=0, VRTNodata=0, separate=True)
        vrt = gdal.BuildVRT(str(outfile), filelist, options=opts)
        vrt.FlushCache()
     
    # write dates file for ts analysis
    with open(download_dir.joinpath('0/dates.csv'), 'w') as f:
        for date in np.unique(sorted(dates)):
            f.write(date)
            f.write('\n')
             

def download_tile(args):

    # split args
    url, filename = args

    if isinstance(filename, str):
        filename = Path(filename)

    # get first response for file Size
    response = requests.get(url, stream=True)

    # check response
    if response.status_code != 200:
        print(' ERROR: Something went wrong.')
        response.raise_for_status()

    # get download size
    total_length = int(response.headers.get('content-length', 0))

    # define chunk_size
    chunk_size = 1024

    # check if file is partially downloaded
    first_byte = filename.stat().st_size if filename.exists() else 0
    
    if first_byte >= total_length:
        return

    while first_byte < total_length:

        # get byte offset for already downloaded file
        header = {"Range": f"bytes={first_byte}-{total_length}"}

        print(f'Downloading tile: {filename.name}')
        response = requests.get(
            url, headers=header, stream=True
        )

        # actual download
        with open(filename, "ab") as file:

            #pbar = tqdm.tqdm(
            #    total=total_length, initial=first_byte, unit='B',
            #    unit_scale=True, desc=' INFO: Downloading: '
            #)
            for chunk in response.iter_content(chunk_size):
                if chunk:
                    file.write(chunk)
                    #pbar.update(chunk_size)
        
        #pbar.close()

        # update first_byte
        first_byte = filename.stat().st_size
