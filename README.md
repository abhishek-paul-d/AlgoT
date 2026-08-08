# Algot - Algorithmic Trading System

An automated trading system that fetches F&O (Futures & Options) market data from Upstox API and stores it in S3 for analysis. The system includes modules for data fetching, volume analysis, and automated order placement with trailing stop functionality.

## Features

- **Automated Authentication**: Secure login to Upstox API using Selenium for web automation and TOTP for 2FA
- **Market Data Collection**: Fetches live F&O market data during trading hours with intelligent scheduling
- **Data Storage**: Efficient storage of market data in Parquet format on AWS S3
- **Volume Analysis**: Specialized module for detecting significant volume spikes and movements
- **Automated Trading**: Order placement system with trailing stop functionality and batch processing
- **Token Management**: Automatic access token refreshment to maintain API connectivity
- **Error Handling**: Comprehensive logging and retry mechanisms for robust operation
- **Scalable Design**: Modular architecture allowing independent operation of different components

## Project Structure

```
algot/
├── data_fetch.py       # Main data fetching logic with Upstox API integration
├── delta_volume.py     # Volume analysis module for detecting significant price/volume movements
├── place_order_trail.py # Order placement system with trailing stop and batch processing
├── main.py             # Simple entry point demonstrating basic usage
├── pyproject.toml      # Project dependencies and metadata
├── uv.lock             # Locked dependencies for reproducible builds
└── .env                # Environment variables (not committed, create from example)
```

## Detailed Module Descriptions

### data_fetch.py
The core data collection module that:
- Authenticates with Upstox API using automated browser Selenium workflow
- Retrieves instrument lists from S3-stored Excel files
- Fetches real-time market quotes in batches to respect API rate limits
- Processes and enriches data with IST timestamps and additional metrics
- Stores aggregated data as daily Parquet files in S3 for efficient querying
- Implements intelligent scheduling for different market phases (pre-market, open, close)

### delta_volume.py
Specialized volume analysis module that:
- Monitors F&O instruments for abnormal volume spikes
- Compares current volume against historical averages
- Identifies potential breakout or breakdown situations
- Uses similar authentication and data fetching patterns as data_fetch.py
- Can be extended to trigger alerts or automated trading signals

### place_order_trail.py
Automated trading execution system featuring:
- Batch order placement (up to 10 orders per API call)
- Concurrent order status checking for improved performance
- Trailing stop functionality for risk management
- Duplicate order prevention through correlation ID tracking
- Excel-based order management stored in S3
- Asynchronous processing for high-throughput order execution
- Thread-safe operations with locking mechanisms

## Installation

### Prerequisites
- Python 3.11 or higher
- UV package installer (for dependency management)
- AWS account with S3 access
- Upstox API credentials with market data and order placement permissions

### Setup Steps

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd algot
   ```

2. **Install dependencies using UV**
   ```bash
   uv sync
   ```

3. **Configure environment variables**
   Create a `.env` file in the project root with:
   ```
   UPSTOX_API_KEY=your_upstox_api_key
   UPSTOX_API_SECRET=your_upstox_api_secret
   UPSTOX_CLIENT_ID=your_upstox_client_id
   UPSTOX_CLIENT_PASS=your_upstox_client_password
   UPSTOX_CLIENT_PIN=your_upstox_client_pin
   AWS_ACCESS_KEY_ID=your_aws_access_key
   AWS_SECRET_ACCESS_KEY=your_aws_secret_key
   AWS_DEFAULT_REGION=your_aws_region
   ```

4. **Prepare S3 resources**
   - Create S3 bucket (default: `upstox02`)
   - Upload required Excel files:
     - `Merged_Equities_BSE_NSE.xlsx` - Contains instrument keys for data fetching
     - `ListStocks.xlsx` - Input orders for the trading module
     - Ensure `OutputOrders.xlsx` exists (will be created automatically if missing)

## Usage

### Running the Data Collection System
```bash
python data_fetch.py
```
This starts the automated data fetcher that:
1. Authenticates with Upstox API
2. Begins collecting F&O market data according to the schedule below
3. Stores data in S3 as daily Parquet files
4. Refreshes authentication tokens automatically

### Running Volume Analysis
```bash
python delta_volume.py
```
Executes the volume spike detection algorithm on current market data.

### Running the Trading System
```bash
python place_order_trail.py
```
Starts the automated order placement system that monitors for new orders and executes them.

## Data Collection Schedule

The system implements different collection frequencies based on market volatility patterns:

- **Pre-Market Session (9:00 AM - 9:59 AM IST)**: 
  - Data collection every minute
  - Captures opening auction and pre-market activity

- **Regular Trading Hours (10:00 AM - 2:59 PM IST)**:
  - Continuous data collection
  - Maximum frequency during peak liquidity periods

- **Closing Session (3:00 PM - 3:30 PM IST)**:
  - Data collection every minute
  - Monitors closing auction and end-of-day positioning

- **Token Refresh Mechanism**:
  - Daily at 8:58 AM IST
  - Ensures uninterrupted API access throughout trading day

*Note: All times are in Indian Standard Time (IST). Collection occurs Monday-Friday only, excluding market holidays.*

## Data Storage Format

### S3 Structure
```
s3://upstox02/
├── equitydata/
│   ├── 2026-08-07_Equity.parquet
│   ├── 2026-08-08_Equity.parquet
│   └── ... (daily files)
├── Merged_Equities_BSE_NSE.xlsx   # Instrument reference file
├── ListStocks.xlsx                # Input orders for trading
└── OutputOrders.xlsx              # Execution results and history
```

### Parquet File Schema
Each daily file contains these columns:
- `instrument_key`: Unique Upstox identifier for the F&O contract
- `Instrument`: Human-readable instrument name (e.g., "NIFTY26AUGFUT")
- `Open`: Opening price for the period
- `High`: Highest price during the period
- `Low`: Lowest price during the period
- `Close`: Closing price for the period
- `Last Price`: Most recent traded price
- `Volume`: Trading volume during the period
- `Average Price`: Volume-weighted average price
- `Open Interest`: Number of outstanding contracts
- `Net Change`: Price change from previous close
- `Total Buy Quantity`: Aggregate buy orders
- `Total Sell Quantity`: Aggregate sell orders
- `Lower Circuit Limit`: Regulatory lower price bound
- `Upper Circuit Limit`: Regulatory upper price bound
- `Last Trade Time`: Timestamp of last trade (converted to IST)
- `OI Day High`: Highest open interest during the day
- `OI Day Low`: Lowest open interest during the day
- `Fetch Timestamp`: When the data was retrieved from API (IST)

## Dependencies

### Core Dependencies
- `selenium==4.15.2`: Browser automation for secure authentication
- `pyotp==2.9.0`: Time-based One-Time Password algorithm for 2FA
- `boto3==1.34.128`: Amazon Web Services SDK for S3 integration
- `pandas==2.2.2`: Data manipulation and analysis library
- `pyarrow==15.0.2`: Efficient columnar storage format (Parquet)
- `apscheduler==3.10.4`: Advanced job scheduling for timed operations
- `requests==2.32.3`: HTTP library for API communication
- `python-dotenv==1.0.1`: Environment variable management
- `webdriver-manager==4.0.1`: Automatic ChromeDriver management
- `httpx==0.27.0`: Asynchronous HTTP client (for trading module)
- `lxml==5.2.2`: XML and HTML parsing
- `openpyxl==3.1.5`: Excel file reading/writing
- `ruff>=0.15.20`: Fast Python linter and formatter

### Development Dependencies
Configured in `pyproject.toml` under `[project.optional-dependencies]` section.

## Configuration

### Data Fetching Parameters (`data_fetch.py`)
- **Chunk Size**: Line 250 - Controls API batch size (default: 490 instruments)
  - Adjust based on API rate limits and instrument count
- **Scheduling**: Lines 328-358 - Modify cron expressions for different market phases
- **S3 Bucket**: Line 32 - Change `bucket_name` variable for different storage
- **File Path**: Line 273 - Modify `generate_daily_filename()` for different storage structure

### Volume Analysis Parameters (`delta_volume.py`)
- Similar configuration to data_fetch.py as it shares core functionality
- Volume threshold settings can be added to detect significant movements

### Trading System Parameters (`place_order_trail.py`)
- **Batch Size**: Line 41 - `MAX_ORDERS_PER_REQUEST` (default: 10)
- **Concurrency**: Line 42 - `MAX_CONCURRENT_DETAIL_REQUESTS` (default: 20)
- **Timeout**: Line 43 - `REQUEST_TIMEOUT` in seconds (default: 5)
- **Scheduling**: Lines 414-425 - Adjust cron expressions and intervals
- **S3 Files**: Lines 34-36 - Modify bucket and file key names

## Monitoring and Logging

The system uses Python's built-in logging module with the following format:
```
TIMESTAMP - LEVEL - MESSAGE
```

Log levels:
- `INFO`: General operational messages
- `WARNING`: Potential issues that don't stop execution
- `ERROR`: Problems that may affect functionality
- `DEBUG`: Detailed diagnostic information (enable by changing logging level)

Logs are printed to stdout and can be redirected to files for persistent monitoring.

## Deployment Considerations

### Production Deployment
1. **Environment**: Run on a reliable server/VPS with stable internet connection
2. **Process Management**: Use systemd, PM2, or similar to ensure continuous operation
3. **Log Rotation**: Implement log rotation to prevent disk space issues
4. **Monitoring**: Set up alerts for login failures, API errors, or S3 upload problems
5. **Backup**: Regularly backup the `.env` file and critical S3 data files

### Security Best Practices
1. **Credentials**: Never commit `.env` file; use secret management in production
2. **Network**: Consider running within a VPC with restricted outbound access
3. **Updates**: Regularly update dependencies to patch security vulnerabilities
4. **Access**: Apply principle of least privilege to AWS IAM roles
5. **Audit**: Enable CloudTrail logging for S3 access monitoring

## Troubleshooting

### Common Issues

**Authentication Failures**
- Verify Upstox credentials are correct and not expired
- Check if 2FA/TOTP is properly configured
- Ensure ChromeDriver can be downloaded and executed
- Verify network allows access to Upstox domains

**S3 Access Problems**
- Confirm AWS credentials have correct S3 permissions
- Verify bucket name and region are correct
- Check network connectivity to AWS endpoints
- Ensure IAM role/user has s3:GetObject, s3:PutObject, s3:ListBucket permissions

**API Rate Limiting**
- Reduce chunk size in data_fetch.py if getting 429 responses
- The system already implements batching to minimize API calls
- Consider adding exponential backoff for retry logic

**Performance Issues**
- Monitor memory usage during large data fetches
- Consider increasing swap memory on low-RAM systems
- The Parquet format is optimized for storage efficiency

### Getting Help
Check the log output for specific error messages. Common patterns:
- `Login failed`: Authentication or 2FA issues
- `Token response is not JSON`: Network or API endpoint problems
- `Error retrieving ticker list from S3`: AWS credentials or bucket access
- `API request error`: Rate limiting, network issues, or invalid parameters

## Extending the System

### Adding New Data Sources
1. Modify `get_ticker_list_from_s3()` to fetch from different S3 keys or formats
2. Update `fetch_fno_data()` to handle different API endpoints or response formats
3. Enhance `epoch_to_ist()` if different timestamp formats are needed

### Implementing New Analysis
1. Create new modules following the pattern of existing files
2. Reuse authentication and utility functions to reduce duplication
3. Store results in S3 using similar Parquet or JSON formats
4. Schedule new analyses using APScheduler in the main execution loop

### Integration with External Systems
1. Add webhook notifications for significant volume spikes or signals
2. Export data to data warehouses (Redshift, BigQuery, Snowflake) for deeper analysis
3. Connect to message queues (Kafka, RabbitMQ) for real-time processing pipelines
4. Develop dashboard visualizations using tools like Grafana, Streamlit, or Plotly

## Disclaimer

**This software is for educational and informational purposes only.** 
Algorithmic trading involves substantial risk of loss and is not suitable for all investors.
Past performance is not indicative of future results.
The authors and contributors assume no liability for any trading losses or damages.
Users should:
- Conduct their own research and due diligence
- Start with paper trading or small position sizes
- Consult with qualified financial professionals
- Comply with all applicable regulations and exchange rules
- Never risk more than they can afford to lose

The Upstox API terms of service and exchange regulations must be followed at all times.
Unauthorized or abusive use of the API may result in access termination.