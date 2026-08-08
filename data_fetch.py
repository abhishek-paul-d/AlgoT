import urllib.parse
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
        
        url = f"https://api-v2.upstox.com/login/authorization/dialog?response_type=code&client_id={apiKey}&redirect_uri=https://127.0.0.1:5000/"
        
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

def epoch_to_ist(epoch_time):
    try:
        epoch_time = str(epoch_time)
        if len(epoch_time) == 13:
            epoch_time = int(epoch_time[:-3])
        else:
            epoch_time = int(epoch_time)
        
        utc_time = datetime.fromtimestamp(epoch_time, tz=timezone.utc)
        ist_tz = pytz.timezone('Asia/Kolkata')
        ist_time = utc_time.astimezone(ist_tz)
        
        return ist_time
    except Exception as e:
        return None

def fetch_fno_data(fnolist, access_token, instrument_mapping):
    if not fnolist:
        logging.warning("Empty instrument list provided")
        return pd.DataFrame()
    
    try:
        instrument_keys = ','.join(map(urllib.parse.quote, fnolist))
        
        url =f'https://api.upstox.com/v2/market-quote/quotes?instrument_key={instrument_keys}'
        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        response_data = response.json() 
        data = response_data.get("data", {})
        
        rows = []
        
        for instrument, details in data.items():
            try:
                row = {
                    "instrument_key": instrument_mapping.get(instrument, None),
                    "Instrument": instrument,
                    "Open": details.get("ohlc", {}).get("open", None),
                    "High": details.get("ohlc", {}).get("high", None),
                    "Low": details.get("ohlc", {}).get("low", None),
                    "Close": details.get("ohlc", {}).get("close", None),
                    "Last Price": details.get("last_price", None),
                    "Volume": details.get("volume", None),
                    "Average Price": details.get("average_price", None),
                    "Open Interest": details.get("oi", None),
                    "Net Change": details.get("net_change", None),
                    "Total Buy Quantity": details.get("total_buy_quantity", None),
                    "Total Sell Quantity": details.get("total_sell_quantity", None),
                    "Lower Circuit Limit": details.get("lower_circuit_limit", None),
                    "Upper Circuit Limit": details.get("upper_circuit_limit", None),
                    "Last Trade Time": epoch_to_ist(details.get("last_trade_time")) if details.get("last_trade_time") else None,
                    "OI Day High": details.get("oi_day_high", None),
                    "OI Day Low": details.get("oi_day_low", None),
                    "Fetch Timestamp": datetime.now(pytz.timezone('Asia/Kolkata'))
                }
                rows.append(row)
            except Exception as e:
                pass
        
        df = pd.DataFrame(rows)
        
        logging.info(f"Successfully fetched data for {len(df)} instruments")
        
        return df
    
    except requests.exceptions.RequestException as e:
        logging.error(f"API request error: {e}")
        return pd.DataFrame()
    except ValueError as e:
        logging.error(f"JSON parsing error: {e}")
        return pd.DataFrame()
    except Exception as e:
        logging.error(f"Unexpected error in fetch_fno_data: {e}")
        return pd.DataFrame()

def fetch_all_fno_data(tickerList, access_token, instrument_mapping, chunk_size=490):
    all_data = []
    
    for i in range(0, len(tickerList), chunk_size):
        chunk = tickerList[i:i + chunk_size]
        logging.info(f"Fetching data for tickers {i + 1} to {i + len(chunk)}...")
        
        try:
            df = fetch_fno_data(chunk, access_token, instrument_mapping)
            
            if not df.empty:
                all_data.append(df)
            else:
                logging.warning(f"No data fetched for chunk {i + 1} to {i + len(chunk)}")
        
        except Exception as e:
            logging.error(f"Error fetching chunk {i + 1} to {i + len(chunk)}: {e}")
    
    return pd.concat(all_data, ignore_index=True) if all_data else pd.DataFrame()

def generate_daily_filename():
    ist_tz = pytz.timezone('Asia/Kolkata')
    current_date = datetime.now(ist_tz).strftime('%Y-%m-%d')
    return f'equitydata/{current_date}_Equity.parquet'

def upload_custom_data_to_s3(custom_df, bucket_name, s3_client):
    try:
        file_name = generate_daily_filename()

        try:
            parquet_obj = s3_client.get_object(Bucket=bucket_name, Key=file_name)
            existing_parquet = parquet_obj['Body'].read()
            existing_df = pd.read_parquet(BytesIO(existing_parquet))
        except s3_client.exceptions.NoSuchKey:
            existing_df = pd.DataFrame()

        combined_df = pd.concat([existing_df, custom_df], ignore_index=True)

        parquet_buffer = BytesIO()
        combined_df.to_parquet(parquet_buffer, index=False)

        s3_client.put_object(Bucket=bucket_name, Key=file_name, Body=parquet_buffer.getvalue())
        logging.info(f"File updated on s3://{bucket_name}/{file_name}")

    except Exception as e:
        logging.error(f"Error uploading file: {e}")

def final_task1():
    global access_token
    try:
        logging.info("Starting data fetch...")
        final_df = fetch_all_fno_data(tickerList, access_token, instrument_mapping)
        
        if final_df.empty:
            logging.warning("Fetched DataFrame is empty.")
        else:
            logging.info(f"Fetched data with shape: {final_df.shape}")
            upload_custom_data_to_s3(final_df, bucket_name, s3_client)
        
        logging.info("Data fetching and upload complete")
    except Exception as e:
        logging.error(f"Error in final_task1: {e}")

def final_task2():
    global access_token
    access_token = auto_login()
    logging.info("Access token refreshed at 9:00 AM")

def schedule_task():
    global access_token
    scheduler = BackgroundScheduler()

    access_token = auto_login()
    
    if not access_token:
        logging.error("Failed to obtain initial access token. Exiting.")
        return

    scheduler.add_job(
        final_task1,
        'cron',
        day_of_week='mon-sun',
        hour='9',
        minute='0-59'
    )

    scheduler.add_job(
        final_task1,
        'cron',
        day_of_week='mon-sun',
        hour='10-14',
        minute='*'
    )

    scheduler.add_job(
        final_task1,
        'cron',
        day_of_week='mon-sun',
        hour='15',
        minute='0-30'
    )

    scheduler.add_job(
        final_task2,
        'cron',
        day_of_week='mon-sun',
        hour='8',
        minute='58'
    )

    scheduler.start()

    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()

if __name__ == "__main__":
    schedule_task()