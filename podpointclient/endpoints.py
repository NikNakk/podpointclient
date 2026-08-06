"""Endpoints from PodPoint"""

AUTH = '/auth'
SESSIONS = '/sessions'
USERS = '/users'
PODS = '/pods'
UNITS = '/units'
CHARGE_SCHEDULES = '/charge-schedules'
CHARGES = '/charges'
CHARGE_OVERRIDE = '/charge-override'
CHARGE_OVERRIDES = '/charge-overrides'
CHARGERS = '/chargers'
CONNECTIVITY_STATUS = '/connectivity-status'
CONNECTIVITY_STATUS_V2 = '/connectivity-status-v2'
FIRMWARE = '/firmware'
ACCESS_STATUS = '/access-status'
AGREEMENTS = '/agreements'
TARIFFS = '/tariffs'
MANUAL_SCHEDULES = '/manual-schedules'
SECURITY_LOGS = '/security-logs'
SUBSCRIPTIONS = '/subscriptions'
DELEGATED_CONTROLS = '/smart-charging/delegated-controls'
DELEGATED_VEHICLES = f'{DELEGATED_CONTROLS}/vehicles'
REWARD_WALLET = '/reward-wallet'
TRANSACTIONS = '/transactions'
PREFERENCES = '/preferences'
STATS = '/stats'
NOTIFICATION_PREFERENCES = '/users/notifications/preferences'
ENERGY_SUPPLIERS = '/energy/suppliers'
REMOTE_LOCK = '/remote-lock'

MOBILE_API_BASE = 'mobile-api.pod-point.com'
API_BASE = f"{MOBILE_API_BASE}/api3/"
API_VERSION = 'v5'
API_BASE_URL = f"https://{API_BASE}{API_VERSION}"

MOBILE_API_BASE_URL = f"https://{MOBILE_API_BASE}"

"""Google endpoint, used for auth"""
GOOGLE_KEY = '?key=AIzaSyCwhF8IOl_7qHXML0pOd5HmziYP46IZAGU'
PASSWORD_VERIFY = f"/verifyPassword{GOOGLE_KEY}"
TOKEN = f"/token{GOOGLE_KEY}"

GOOGLE_BASE = 'www.googleapis.com/identitytoolkit/v3/relyingparty'
GOOGLE_BASE_URL = f"https://{GOOGLE_BASE}"

GOOGLE_TOKEN_BASE = 'securetoken.googleapis.com/v1'
GOOGLE_TOKEN_BASE_URL = f"https://{GOOGLE_TOKEN_BASE}"
