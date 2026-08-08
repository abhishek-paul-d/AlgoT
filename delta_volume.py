import time 
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
import pyotp
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import urllib
import boto3
import pandas as pd
from io import StringIO, BytesIO
import os
from datetime import datetime, timezone, timedelta
import pytz
import schedule
import requests
import json
from apscheduler.schedulers.background import BackgroundScheduler
import logging
from dotenv import load_dotenv
from webdriver_manager.chrome import ChromeDriverManager
load_dotenv()

logging.basicConfig(level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

apiKey = os.getenv('UPSTOX_API_KEY')
secretKey = os.getenv('UPSTOX_API_SECRET')
rurl = urllib.parse.quote('https://127.0.0.1:5000/',safe="")
bucket_name = 'upstox02'

access_token = None

def get_ticker_list_from_s3(bucket_name='upstox02', file_key='Merged_Equities_BSE_NSE.xlsx'):
    try:
        s3_client = boto3.client('s3')
        
        response = s3_client.get_object(Bucket=bucket_name, Key=file_key)
        
        ticker_df = pd.read_excel(BytesIO(response['Body'].read()))

        instrument_mapping = dict(zip(ticker_df['instrument_key'], ticker_df['instrument_key']))

        tickerList = list(instrument_mapping.keys())
        
        logging.info(f"Successfully retrieved {len(tickerList)} tickers from S3")
        return tickerList, instrument_mapping
    
    except Exception as e:
        logging.error(f"Error retrieving ticker list from S3: {e}")
        return [], {}

tickerList, instrument_mapping = get_ticker_list_from_s3()

s3_client = boto3.client('s3')

def auto_login():
    try:
        options = Options()
        options.add_argument('--no-sandbox')
        options.add_argument('--headless=new')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--remote-debugging-port=9222')
        
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        
        url = "https://api-v2.upstox.com/login/authorization/dialog?response_type=code&client_id=cbe822d5-1f9b-47c1-a1f2-42ae9ee4ad6f&redirect_uri=https://127.0.0.1:5000/"
        
        driver.get(url)
        
        def wait_for_page_load(driver, timeout=30):
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
        
        wait_for_page_load(driver)
        
        client_id = os.getenv('UPSTOX_CLIENT_ID')
        username_input_xpath = '//*[@id="mobileNum"]'
        
        username_input_element = driver.find_element(By.XPATH, username_input_xpath)
        username_input_element.clear()
        username_input_element.send_keys(client_id)
        
        get_otp_button_xpath = '//*[@id="getOtp"]'
        
        get_otp_button_element = driver.find_element(By.XPATH, get_otp_button_xpath)
        get_otp_button_element.click()
        
        client_pass = os.getenv('UPSTOX_CLIENT_PASS')
        client_pass = pyotp.TOTP(client_pass).now()
        time.sleep(5)
        
        password_input_xpath = '//*[@id="otpNum"]'
        
        password_input_element = driver.find_element(By.XPATH, password_input_xpath)
        password_input_element.clear()
        password_input_element.send_keys(client_pass)
        
        continue_button_xpath = '//*[@id="continueBtn"]'
        
        continue_button_element = driver.find_element(By.XPATH, continue_button_xpath)
        continue_button_element.click()
        time.sleep(5)
        
        client_pin = os.getenv('UPSTOX_CLIENT_PIN')
        
        pin_input_xpath = '//*[@id="pinCode"]'
        
        pin_input_element = driver.find_element(By.XPATH, pin_input_xpath)
        pin_input_element.clear()
        pin_input_element.send_keys(client_pin)
        
        original_url = driver.current_url
        
        pin_continue_button_xpath = '//*[@id="pinContinueBtn"]'
        
        pin_continue_button_element = driver.find_element(By.XPATH, pin_continue_button_xpath)
        pin_continue_button_element.click()
        
        WebDriverWait(driver, 30).until(EC.url_changes(original_url))
        
        redirected_url = driver.current_url
        redirected_url = redirected_url.split("?code=")
        
        code = redirected_url[1]
        
        url = 'https://api.upstox.com/v2/login/authorization/token'
        
        headers = {
            'accept': 'application/json',
            'Api-Version': '2.0',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        data = {
            'code': code,
            'client_id': apiKey,
            'client_secret': secretKey,
            'redirect_uri': 'https://127.0.0.1:5000/',
            'grant_type': 'authorization_code'
        }
        
        response = requests.post(url, headers=headers, data=data)
        try:
            json_response = response.json()
        except ValueError:
            logging.error(f"Token response is not JSON: {response.text}")
            driver.quit()
            return None
        
        access_token = json_response.get('access_token')
        if not access_token:
            logging.error(f"Token request failed: status={response.status_code}, response={json_response}")
            driver.quit()
            return None
        
        driver.quit()
        logging.info("Login successful")
        return str(access_token)
    
    except Exception as e:
        logging.error(f"Login failed: {e}")
        return None
    

    
