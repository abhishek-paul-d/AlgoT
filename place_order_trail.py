import io
import time
import logging
import threading
import asyncio
from datetime import datetime

import boto3
import httpx
import pandas as pd
import pyotp
import requests
import os
from dotenv import load_dotenv
from botocore.exceptions import ClientError
from apscheduler.schedulers.background import BackgroundScheduler
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

apiKey = os.getenv("UPSTOX_API_KEY")
secretKey = os.getenv("UPSTOX_SECRET_KEY")

BUCKET_NAME = "upstox02"
INPUT_FILE_KEY = "ListStocks.xlsx"
OUTPUT_FILE_KEY = "OutputOrders.xlsx"

MULTI_ORDER_URL = "https://api.upstox.com/v2/order/multi/place"
ORDER_DETAILS_URL = "https://api.upstox.com/v2/order/details"

MAX_ORDERS_PER_REQUEST = 10
MAX_CONCURRENT_DETAIL_REQUESTS = 20
REQUEST_TIMEOUT = 5

sync_lock = threading.Lock()
access_token = None


def auto_login():
    try:
        options = Options()
        options.add_argument('--no-sandbox')
        options.add_argument('--headless')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--remote-debugging-port=9222')

        driver = webdriver.Chrome(options=options)

        url = f"https://api-v2.upstox.com/login/authorization/dialog?response_type=code&client_id={apiKey}&redirect_uri=https://127.0.0.1:5000/"
        driver.get(url)

        def wait_for_page_load(driver, timeout=30):
            WebDriverWait(driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )

        wait_for_page_load(driver)

        client_id = os.getenv("UPSTOX_CLIENT_ID")
        username_input_xpath = '//*[@id="mobileNum"]'

        username_input_element = driver.find_element(By.XPATH, username_input_xpath)
        username_input_element.clear()
        username_input_element.send_keys(client_id)

        get_otp_button_xpath = '//*[@id="getOtp"]'

        get_otp_button_element = driver.find_element(By.XPATH, get_otp_button_xpath)
        get_otp_button_element.click()

        client_pass = os.getenv("UPSTOX_CLIENT_PASS")
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

        client_pin = os.getenv("UPSTOX_CLIENT_PIN")

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


# Read the INPUT file from S3
def read_excel_from_s3(bucket_name, file_key):
    s3 = boto3.client("s3")
    buffer = io.BytesIO()
    s3.download_fileobj(bucket_name, file_key, buffer)
    buffer.seek(0)

    df = pd.read_excel(buffer)
    df.columns = df.columns.str.strip()
    return df

# Read the OUTPUT file from S3.
def read_output_df(bucket_name, file_key):
    s3 = boto3.client("s3")

    try:
        buffer = io.BytesIO()
        s3.download_fileobj(bucket_name, file_key, buffer)
        buffer.seek(0)

        df = pd.read_excel(buffer)
        df.columns = df.columns.str.strip()
        return df

    except ClientError:
        return pd.DataFrame()


# Upload a DataFrame back to S3 (used for the output file)
def upload_excel_to_s3(df, bucket_name, file_key):
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    buffer.seek(0)

    boto3.client("s3").upload_fileobj(buffer, bucket_name, file_key)


# Compare input rows against what's already in the output file,
# and return only the rows that haven't been placed yet.
def find_new_orders(input_df, output_df):
    processed = set()
    if not output_df.empty:
        processed = set(
            output_df["correlation_id"].astype(str).str.strip()
        )

    return input_df[~input_df["correlation_id"].astype(str).str.strip().isin(processed)]


# Batching and api call
async def place_orders(client, headers, orders):
    batches = [
        orders[i: i + MAX_ORDERS_PER_REQUEST]
        for i in range(0, len(orders), MAX_ORDERS_PER_REQUEST)
    ]

    async def send_batch(batch):
        try:
            response = await client.post(MULTI_ORDER_URL, headers=headers, json=batch)
            body = response.json()
        except Exception as e:
            body = {"status": "error", "message": str(e)}
        return batch, body

    return await asyncio.gather(*[send_batch(batch) for batch in batches])


#  Fetch order_id / status / message / timestamp from the order details API
async def fetch_order_details(client, headers, results):

    detail_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DETAIL_REQUESTS)

    async def fetch_status(order_id):
        async with detail_semaphore:
            try:
                response = await client.get(
                    ORDER_DETAILS_URL, headers=headers, params={"order_id": order_id}
                )

                try:
                    body = response.json()
                except Exception:
                    return order_id, {"status": "error", "message": response.text}

                if body.get("status") == "success":
                    data = body.get("data", {}) or {}
                    return order_id, {
                        "status": data.get("status"),
                        "message": data.get("status_message"),
                    }

                msg = None
                if body.get("errors"):
                    msg = body["errors"][0].get("message")
                return order_id, {"status": "error", "message": msg or body.get("message")}

            except httpx.RequestError as e:
                return order_id, {"status": "error", "message": str(e)}

    order_id_to_corr = {
        r["order_id"]: corr for corr, r in results.items() if r.get("order_id")
    }

    if order_id_to_corr:
        detail_responses = await asyncio.gather(*[fetch_status(oid) for oid in order_id_to_corr])
        for order_id, detail in detail_responses:
            corr = order_id_to_corr[order_id]
            results[corr]["status"] = detail.get("status")
            results[corr]["message"] = detail.get("message")

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in results.values():
        r["timestamp"] = timestamp

    return results


# Place orders for any new rows and return the updated output_df + results
def process_new_orders_and_place(input_df, output_df, access_token):
    new_rows = find_new_orders(input_df, output_df)

    if new_rows.empty:
        logging.info("No new orders")
        return output_df, {}

    logging.info(f"{len(new_rows)} new order(s) detected")

    orders = []
    for _, row in new_rows.iterrows():
        orders.append({
            "correlation_id": str(row["correlation_id"]).strip(),
            "quantity": int(row["quantity"]),
            "product": row["product"],
            "validity": row["validity"],
            "price": float(row["price"]),
            "tag": row["tag"],
            "instrument_token": row["instrument_token"],
            "order_type": row["order_type"],
            "transaction_type": row["transaction_type"],
            "disclosed_quantity": int(row["disclosed_quantity"]),
            "trigger_price": float(row["trigger_price"]),
            "is_amo": bool(row.get("is_amo", False)),
            "slice": bool(row.get("slice", False)),
            "market_protection": int(row["market_protection"]),
        })

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async def run():
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            batch_responses = await place_orders(client, headers, orders)

            results = {}
            for batch, body in batch_responses:
                if not isinstance(body, dict) or body.get("status") != "success":
                    if isinstance(body, dict):
                        msg = body.get("message")
                        if not msg and body.get("errors"):
                            msg = body["errors"][0].get("message")
                    else:
                        msg = str(body)
                    for order in batch:
                        results[order["correlation_id"]] = {
                            "order_id": None, "status": "error", "message": msg,
                        }
                    continue

                returned = {}
                for item in body.get("data", []):
                    corr = item.get("correlation_id", "").split("_")[0]
                    returned[corr] = item.get("order_id")

                errored = {}
                for err in body.get("errors", []):
                    corr = str(err.get("correlation_id", "")).split("_")[0]
                    errored[corr] = err.get("message") or err.get("errorCode")

                for order in batch:
                    corr = order["correlation_id"]
                    if corr in returned:
                        results[corr] = {"order_id": returned[corr], "status": None, "message": None}
                    else:
                        results[corr] = {
                            "order_id": None,
                            "status": "error",
                            "message": errored.get(corr, "not returned by API"),
                        }

            return await fetch_order_details(client, headers, results)

    results = asyncio.run(run())

    for r in results.values():
        if r.get("status") == "error":
            r["message"] = f"Order not executed due to: {r.get('message')}"

    rows = []
    for _, row in new_rows.iterrows():
        corr = str(row["correlation_id"]).strip()
        result = results[corr]

        record = row.to_dict()
        record["order_id"] = result.get("order_id")
        record["status"] = result.get("status")
        record["message"] = result.get("message")
        record["timestamp"] = result.get("timestamp")

        rows.append(record)

    output_df = pd.concat(
        [output_df, pd.DataFrame(rows)],
        ignore_index=True
    )

    return output_df, results


def final_task1():
    if not sync_lock.acquire(blocking=False):
        logging.info("Previous execution still running. Skipping...")
        return

    try:
        input_df = read_excel_from_s3(BUCKET_NAME, INPUT_FILE_KEY)
        output_df = read_output_df(BUCKET_NAME, OUTPUT_FILE_KEY)

        output_df, results = process_new_orders_and_place(input_df, output_df, access_token)

        if not results:
            return

        upload_excel_to_s3(output_df, BUCKET_NAME, OUTPUT_FILE_KEY)

        placed = sum(1 for r in results.values() if r.get("order_id"))
        logging.info(f"Processed {len(results)} order(s): {placed} placed, {len(results) - placed} error.")

    finally:
        sync_lock.release()


def schedule_task():
    global access_token
    scheduler = BackgroundScheduler()

    access_token = auto_login()
    if not access_token:
        logging.error("Failed to obtain initial access token. Exiting.")
        return

    final_task1()
    scheduler.add_job(final_task1, "interval", seconds=5)

    scheduler.add_job(
        final_task1, "cron",
        day_of_week="mon-sun", hour="9", minute="0-59", second="*/5",
    )
    scheduler.add_job(
        final_task1, "cron",
        day_of_week="mon-sun", hour="10-14", minute="*", second="*/5",
    )
    scheduler.add_job(
        final_task1, "cron",
        day_of_week="mon-sun", hour="15", minute="0-30", second="*/5",
    )

    scheduler.start()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    schedule_task()