"""Load environment variables and shared constants."""

import os
from dotenv import load_dotenv

load_dotenv()

BRAPI_TOKEN: str = os.environ["BRAPI_TOKEN"]
BRAPI_BASE_URL: str = "https://brapi.dev/api"

# Inflation target for Adjusted Graham Number
IPCA_RATE: float = float(os.getenv("IPCA_RATE", "0.045"))

# Graham criteria thresholds
PE_MAX = 15.0
PB_MAX = 1.5
PEPB_MAX = 22.5   # P/E × P/B combined ceiling (Graham's rule)
DE_MAX = 1.0
CR_MIN = 2.0

# Dividend history window (years)
DIVIDEND_YEARS = 3
