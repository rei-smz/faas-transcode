import asyncio
import logging
import os
import time
import json
from tempfile import NamedTemporaryFile
from minio import Minio
from minio.error import S3Error

if os.name == 'nt':
  SHELL = 'pwsh'
else:
  SHELL = 'sh'

MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY')
BUCKET_NAME = os.getenv('BUCKET_NAME')

minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)

async def run_ffmpeg(args,
                     tmp_in,
                     tmp_out):
  resolution = args.get('resolution', '1280x720')
  acodec = args.get('acodec', 'copy')
  vcodec = args.get('vcodec', '')
  if resolution != 'no':
    resolution_cmd = f'-s {resolution}'
  else:
    resolution_cmd = ''
  codec = ''
  if acodec != '':
    codec += ' -acodec ' + acodec
  if vcodec != '':
    codec += ' -vcodec ' + vcodec
  cmd = f'ffmpeg -hide_banner -f mp4 -loglevel warning -y -i {tmp_in} {resolution_cmd} {codec} {tmp_out}'
  full_cmd = f'{SHELL} -c "{cmd}"'
  ts = time.time()
  logging.debug(f'full_cmd = {full_cmd}')
  process = await asyncio.create_subprocess_exec(SHELL, "-c", cmd)
  await process.wait()
  logging.debug(f"done ffmpeg in {time.time() - ts} s")
  if process.returncode != 0:
    return f"Fail to execute {cmd}"
  else:
     return "Success"


def handle(event, context):
    if event.method != "POST":
      return {
        "statusCode": 405,
        "body": "Method not allowed"
      }
    
    try:
        body = json.loads(event.body.decode('utf-8'))
    except json.JSONDecodeError:
        return {"statusCode": 400, "body": "Invalid JSON"}
    
    path = body.get('path')
    obj_name = body.get('object')
    args = body.get('args', {})
    video_format = args.get('format', 'mp4')

    if not path:
        return {"statusCode": 400, "body": "Path is required"}

    # get video
    input_tmp = obj_name
    try:
        minio_client.fget_object(BUCKET_NAME, path + '/' + obj_name, input_tmp)
    except S3Error as e:
        logging.error(f"MinIO Error: {e}")
        return {"statusCode": 500, "body": f"Error downloading file: {e}"}
    
    # run trancoding
    output_tmp = "out." + video_format
    result = asyncio.run(run_ffmpeg(args, input_tmp, output_tmp))
    if "Fail" in result:
        os.remove(input_tmp)
        return {"statusCode": 500, "body": result}

    # upload result
    try:
        minio_client.fput_object(BUCKET_NAME, path + '/' + output_tmp, output_tmp)
    except S3Error as e:
        logging.error(f"MinIO Error: {e}")
        os.remove(input_tmp)
        os.remove(output_tmp)
        return {"statusCode": 500, "body": f"Error uploading file: {e}"}

    os.remove(input_tmp)
    os.remove(output_tmp)

    return {"statusCode": 200, "body": "success"}