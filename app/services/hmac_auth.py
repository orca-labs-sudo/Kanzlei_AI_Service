import hmac
import hashlib
import time
import logging
from app.config import settings

logger = logging.getLogger(__name__)

TIMESTAMP_TOLERANCE_SECONDS = 60

def generate_ki_signature(timestamp: str = None) -> str:
    """
    Generiert eine HMAC-SHA256 Signatur basierend auf Timestamp und dem Secret-Token.
    """
    if timestamp is None:
        timestamp = str(int(time.time()))
        
    secret = settings.backend_api_token.encode('utf-8')
    message = timestamp.encode('utf-8')
    
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{timestamp}.{signature}"

def verify_ki_signature(auth_header: str) -> bool:
    """
    Prüft ob der Authorization/X-KI-Signature Header gültig ist.
    Erwartetes Format: "timestamp.signature"
    """
    if not auth_header:
        return False
        
    try:
        if auth_header.startswith("Bearer "):
            auth_header = auth_header.replace("Bearer ", "")
            
        parts = auth_header.split('.')
        if len(parts) != 2:
            return False
            
        timestamp_str, provided_signature = parts
        
        request_time = int(timestamp_str)
        current_time = int(time.time())
        
        if abs(current_time - request_time) > TIMESTAMP_TOLERANCE_SECONDS:
            logger.warning(f"HMAC Signatur abgelehnt: Timestamp zu alt/weit abweichend ({request_time} vs {current_time})")
            return False
            
        expected_signature = generate_ki_signature(timestamp_str).split('.')[1]
        
        return hmac.compare_digest(expected_signature, provided_signature)
        
    except Exception as e:
        logger.error(f"Fehler bei HMAC Signatur-Verifizierung in AI-Service: {e}")
        return False
