"""
Google Sheets Connection Manager with Connection Pooling & Caching
Solves SSL connection exhaustion by reusing gspread client across requests
"""
import gspread
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass
import threading
import time
import os
import pathlib
from ssl import SSLEOFError, SSLError as SSLErrorBase
from functools import wraps
import requests.exceptions

# Configuration
SHEET_NAME = 'schedule'
DIR = pathlib.Path(__file__).parent.parent.resolve()
CREDENTIALS_PATH = os.path.join(DIR, 'credentials.json')
CACHE_TTL_SECONDS = 300  # 5 minutes default
MAX_RETRIES = 3
RETRY_BACKOFF_FACTOR = 2


@dataclass
class CacheEntry:
    """Cached worksheet data with TTL"""
    data: Any
    cached_at: datetime
    ttl_seconds: int
    
    def is_expired(self) -> bool:
        return datetime.utcnow() - self.cached_at > timedelta(seconds=self.ttl_seconds)


class GoogleSheetsManager:
    """
    Singleton manager for Google Sheets connections with caching
    
    Features:
    - Single gspread client instance (connection pooling)
    - In-memory cache with configurable TTL
    - Automatic retry with exponential backoff
    - Thread-safe operations
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._client: Optional[gspread.Client] = None
        self._cache: Dict[str, CacheEntry] = {}
        self._cache_lock = threading.Lock()
        self._initialized = True
        self._last_connection_time: Optional[datetime] = None
    
    def _get_client(self) -> gspread.Client:
        """Get or create the gspread client (singleton pattern)"""
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = gspread.service_account(CREDENTIALS_PATH)
                    self._last_connection_time = datetime.utcnow()
                    print(f"✅ Created new gspread client at {self._last_connection_time}")
        return self._client
    
    def _retry_on_ssl_error(self, func):
        """Decorator for retrying operations on SSL errors"""
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            
            for attempt in range(MAX_RETRIES):
                try:
                    return func(*args, **kwargs)
                except SSLEOFError as e:
                    last_exception = e
                    if attempt < MAX_RETRIES - 1:
                        wait_time = RETRY_BACKOFF_FACTOR ** attempt
                        print(f"⚠️ SSLEOFError on attempt {attempt + 1}, retrying in {wait_time}s...")
                        time.sleep(wait_time)
                        
                        # Recreate client on SSL errors
                        with self._lock:
                            self._client = None
                    else:
                        print(f"❌ SSLEOFError after {MAX_RETRIES} attempts")
                except Exception as e:
                    # For other errors, fail immediately
                    print(f"❌ Error in Google Sheets operation: {type(e).__name__}: {e}")
                    raise
            
            raise last_exception
        
        return wrapper
    
    def _get_from_cache(self, cache_key: str) -> Optional[Any]:
        """Get data from cache if not expired"""
        with self._cache_lock:
            if cache_key in self._cache:
                entry = self._cache[cache_key]
                if not entry.is_expired():
                    print(f"✅ Cache HIT for {cache_key}")
                    return entry.data
                else:
                    print(f"⏰ Cache EXPIRED for {cache_key}")
                    del self._cache[cache_key]
        return None
    
    def _set_cache(self, cache_key: str, data: Any, ttl_seconds: int):
        """Store data in cache"""
        with self._cache_lock:
            self._cache[cache_key] = CacheEntry(
                data=data,
                cached_at=datetime.utcnow(),
                ttl_seconds=ttl_seconds
            )
            print(f"💾 Cached data for {cache_key} (TTL: {ttl_seconds}s)")
    
    def clear_cache(self, cache_key: Optional[str] = None):
        """Clear cache entry or entire cache"""
        with self._cache_lock:
            if cache_key:
                self._cache.pop(cache_key, None)
                print(f"🗑️ Cleared cache for {cache_key}")
            else:
                self._cache.clear()
                print("🗑️ Cleared entire cache")
    
    def get_student_history(
        self, 
        worksheet_name: str, 
        use_cache: bool = True,
        cache_ttl: int = CACHE_TTL_SECONDS
    ) -> List[List[Any]]:
        """
        Get student history from Google Sheets
        
        Args:
            worksheet_name: Name of the worksheet (student's Google Sheet name)
            use_cache: Whether to use caching (default: True)
            cache_ttl: Cache TTL in seconds (default: 300)
        
        Returns:
            List of batch_get results: [lessons_data, balance_data]
        """
        cache_key = f"student_history:{worksheet_name}"
        
        # Check cache first
        if use_cache:
            cached_data = self._get_from_cache(cache_key)
            if cached_data is not None:
                return cached_data
        
        # Fetch from Google Sheets with retry logic
        result = self._fetch_with_retry(worksheet_name)
        
        # Cache the result
        if use_cache:
            self._set_cache(cache_key, result, cache_ttl)
        
        return result
    
    def _fetch_with_retry(self, worksheet_name: str) -> List[List[Any]]:
        """Fetch data with retry logic"""
        last_exception = None
        
        for attempt in range(MAX_RETRIES):
            try:
                print(f"📊 Fetching data from Google Sheets for worksheet: {worksheet_name}")
                
                client = self._get_client()
                sheet = client.open(SHEET_NAME)
                worksheet = sheet.worksheet(worksheet_name)
                
                result = worksheet.batch_get(["B5:C10000", "E3:E4"])
                return result
                
            except (SSLEOFError, SSLErrorBase, requests.exceptions.SSLError) as e:
                last_exception = e
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_BACKOFF_FACTOR ** attempt
                    print(f"⚠️ SSL Error on attempt {attempt + 1}, retrying in {wait_time}s...")
                    time.sleep(wait_time)

                    # Recreate client on SSL errors
                    with self._lock:
                        self._client = None
                else:
                    print(f"❌ SSL Error after {MAX_RETRIES} attempts")
            except Exception as e:
                # For other errors, fail immediately
                print(f"❌ Error in Google Sheets operation: {type(e).__name__}: {e}")
                raise
        
        raise last_exception
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics for monitoring"""
        with self._cache_lock:
            total_entries = len(self._cache)
            expired_entries = sum(1 for entry in self._cache.values() if entry.is_expired())
            
            return {
                "total_entries": total_entries,
                "active_entries": total_entries - expired_entries,
                "expired_entries": expired_entries,
                "cache_keys": list(self._cache.keys()),
                "last_connection": self._last_connection_time.isoformat() if self._last_connection_time else None
            }


# Global singleton instance
_sheets_manager = GoogleSheetsManager()


def get_sheets_manager() -> GoogleSheetsManager:
    """Get the global GoogleSheetsManager instance"""
    return _sheets_manager
