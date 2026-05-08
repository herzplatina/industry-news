#!/bin/bash
cd /Users/shipra/industry-news
source venv/bin/activate
mkdir -p logs
python3 -m src.main >> "logs/digest_$(date +%Y-%m-%d).log" 2>&1
