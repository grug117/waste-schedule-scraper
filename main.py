from bs4 import BeautifulSoup
from http import cookies
from datetime import datetime

import os
import logging
import requests
import boto3
import json

log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
logging.basicConfig(format = log_format, level = logging.INFO)
logger = logging.getLogger(__name__)

def set_session_id(session, url):
    logger.info('set_session_id - start')
    response = session.get(url)

    if response.status_code != 200:
        raise Exception('could not get session id')

    c = cookies.SimpleCookie()
    c.load(response.request.headers['cookie'])

    session_id = c.get('ASP.NET_SessionId').value
    logger.info(f'session_id:{session_id}')
    # ASP.NET_SessionId cookie is set on the session (requests.Session) to be used in subsequent requests
    logger.info('set_session_id - end')


def get_waste_schedule_raw_html(session, url):
    logger.info('get_waste_schedule_raw_html - start')
    house_num = os.environ['HOUSE_NUM']
    postcode = os.environ['POSTCODE']

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    payload = {
        'personInfo.person1.RequiredFields':'%7Cadd%7C',
        'personInfo.person1.Title': '',
        'personInfo.person1.FirstName': '',
        'personInfo.person1.LastName': '',
        'personInfo.person1.HouseNumberOrName': house_num,
        'personInfo.person1.Postcode': postcode,
        'person1_FindAddress': 'Find+address'
    }

    response = session.post(url, data=payload, headers=headers)

    if response.status_code != 200:
        raise Exception('waste schedule not found')

    logger.info('get_waste_schedule_raw_html - end')
    return response.content

def convert_string_collection_date(date):
    collection_date = date.strip()
    # Parse the collection date using the datetime module
    collection_date = datetime.strptime(collection_date, '%A, %B %d, %Y')
    # Convert the collection date to the YYYY-MM-DD format
    collection_date = collection_date.strftime('%Y-%m-%d')

    return collection_date

def extract_schedule_data_from_html(html):
    logger.info('extract_schedule_data_from_html - start')
    schedule_data = []

    next_collection_info = find_next_collection_info(html)

    if next_collection_info is not None:
        schedule_data.append(next_collection_info)

    future_collection_info = find_future_collection_info(html)

    schedule_data = schedule_data + future_collection_info

    logger.info('extract_schedule_data_from_html - end')
    return schedule_data

def find_future_collection_info(html):
    future_collections = []
    table = None

    soup = BeautifulSoup(html, 'html.parser')
    fieldsets = soup.find_all('fieldset')

    for fs in fieldsets:
      label = fs.find('label')

      if label and label.text == "Your next collection days are":
        tbl = fs.find('table')

        if tbl:
          table = tbl
          break

    if table is None:
      raise Exception("Could not find table of collection dates in scraped content")

    logger.info('Got table with data, attempting to parse for schedule info')

    for row in table.find_all('tr'):
        cols = row.find_all('td')
        if len(cols) == 2:
            # Get the text in the first column (Collection date) and convert it
            collection_date = convert_string_collection_date(cols[0].text)

            # Get the text in the second column (Bin type)
            bin_type = cols[1].text.strip()
            future_collections.append({'collection_date': collection_date, 'bin_type': bin_type})

    if len(future_collections) == 0:
        raise Exception('Unable to parse schedule data from table')

    logger.info(f'got and parsed {len(future_collections)} items from schedule')

    return future_collections

def find_next_collection_info(html):
    soup = BeautifulSoup(html, 'html.parser')

    next_bin_date = soup.find(class_='ui-bin-next-date').get_text()
    next_bin_type = soup.find(class_='ui-bin-next-type').get_text()

    if next_bin_type == "Today":
        return None

    return {
        'collection_date': convert_string_collection_date(next_bin_date),
        'bin_type': next_bin_type.strip()
    }

def upload_schedule_data_to_s3(bucket_name, data):
    logger.info('upload_schedule_data_to_s3 - start')
    s3 = boto3.resource('s3')

    # TODO: rename to be date specific
    key = datetime.now().strftime('%Y%m%d') + '.json'

    json_string = json.dumps(data)

    logger.info(f'upload to {bucket_name}/{key}')
    s3.Object(bucket_name, key).put(Body=json_string)
    logger.info('upload_schedule_data_to_s3 - end')

def main():
    url = os.environ['URL']
    bucket_name = os.environ['BUCKET_NAME']

    session = requests.Session()
    set_session_id(session, url)

    waste_schedule_html = get_waste_schedule_raw_html(session, url)
    schedule_data = extract_schedule_data_from_html(waste_schedule_html)
    print(schedule_data)

    upload_schedule_data_to_s3(bucket_name, schedule_data)
