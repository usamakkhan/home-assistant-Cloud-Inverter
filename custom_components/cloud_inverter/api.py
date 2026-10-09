"""API Client for Cloud Inverter."""
import logging
import aiohttp
import asyncio
import base64
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    ENDPOINT_LOGIN,
    ENDPOINT_MEMBER_DATA,
    ENDPOINT_ALL_MEMBERS,
    ENDPOINT_GROUP_LIST,
    ENDPOINT_GROUP_DETAIL,
    ENDPOINT_INVERTER_DETAIL,
)

_LOGGER = logging.getLogger(__name__)

# Public values used by the portal's request signer (umi.5294b0a9.js).
_SIGN_KEY = b"05469137076236813460585715952089"
_SIGN_IV = b"5161557162012237"


def sign_payload(payload: dict[str, Any]) -> str:
    """Sign request fields in the same order and format as the portal client."""
    fields = []
    for key in sorted(payload):
        value = payload[key]
        if value is None or isinstance(value, bool) or value == "":
            continue
        text = "Array" if isinstance(value, list) else str(value)
        fields.append(f"{key}={text}")
    message = ("&".join(fields) + "&" + _SIGN_KEY.decode()).encode()
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(message) + padder.finalize()
    encryptor = Cipher(algorithms.AES(_SIGN_KEY), modes.CBC(_SIGN_IV)).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def signed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Add a fresh signature without mutating the request fields."""
    return {"sign": sign_payload(payload), **payload}


class CloudInverterAPI:
    """Class to communicate with Cloud Inverter API."""

    def __init__(
        self,
        username: str,
        password: str,
        session: aiohttp.ClientSession | None = None,
        *,
        close_session: bool = False,
    ):
        """Initialize the API client."""
        self.username = username
        self.password = password
        self.session = session
        self.token = None
        self.member_auto_id = None
        self.goods_id = None
        self._close_session = close_session

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get aiohttp session."""
        if self.session is None:
            self.session = aiohttp.ClientSession()
            self._close_session = True
        return self.session

    async def close(self):
        """Close the session."""
        if self._close_session and self.session:
            await self.session.close()

    async def login(self) -> bool:
        """Login to Cloud Inverter API."""
        try:
            session = await self._get_session()
            
            # Prepare login payload
            payload = signed_payload({
                "MemberID": self.username,
                "Password": self.password,
                "remember": True,
                "type": "1"
            })
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": ""
            }
            
            async with asyncio.timeout(30):
                async with session.post(ENDPOINT_LOGIN, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "ok":
                            self.token = data.get("token")
                            self.member_auto_id = data.get("MemberAutoID")
                            _LOGGER.info("Successfully logged in to Cloud Inverter")
                            return True
                        else:
                            # Rejection may also indicate an outdated signature or token.
                            _LOGGER.error(
                                "Cloud Inverter login rejected (status: %s, code: %s)",
                                data.get("status"),
                                data.get("code"),
                            )
                            return False
                    else:
                        _LOGGER.error("Cloud Inverter login HTTP status %s", response.status)
                        return False
                    
        except asyncio.TimeoutError:
            _LOGGER.error("Login timeout - could not connect to Cloud Inverter API")
            return False
        except aiohttp.ClientError as err:
            _LOGGER.error("Cloud Inverter login connection error: %s", type(err).__name__)
            return False
        except Exception:
            _LOGGER.exception("Unexpected Cloud Inverter login error")
            return False

    async def get_member_data(self) -> dict[str, Any]:
        """Get member data."""
        if not self.token or not self.member_auto_id:
            if not await self.login():
                return {}
            
        try:
            session = await self._get_session()
            
            payload = signed_payload({
                "MemberAutoID": self.member_auto_id,
                "language": "en-US",
            })
            
            headers = {
                "Content-Type": "application/json",
                "authorization": self.token,
                "cookie": "timezone=Asia%2FKarachi"
            }
            
            async with asyncio.timeout(30):
                async with session.post(ENDPOINT_MEMBER_DATA, json=payload, headers=headers) as response:
                    if response.status == 200:
                        return await response.json()
                    return {}
                    
        except Exception as err:
            _LOGGER.error("Error getting member data: %s", err)
            return {}

    async def get_group_list(self) -> list[dict[str, Any]]:
        """Get list of inverter groups."""
        if not self.token or not self.member_auto_id:
            if not await self.login():
                return []
            
        try:
            session = await self._get_session()
            
            payload = signed_payload({
                "MemberAutoID": self.member_auto_id,
                "inputValue": "",
            })
            
            headers = {
                "Content-Type": "application/json",
                "authorization": self.token,
                "cookie": "timezone=Asia%2FKarachi"
            }
            
            async with asyncio.timeout(30):
                async with session.post(ENDPOINT_GROUP_LIST, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        groups = data.get("AllGroupList", [])
                        _LOGGER.debug("Group list contains %d groups", len(groups))
                        if groups and len(groups) > 0:
                            # Store the AutoID from the first group (this is GroupAutoID)
                            first_group = groups[0]
                            group_auto_id = str(first_group.get("AutoID"))
                            _LOGGER.info("Found inverter group")
                            
                            # Now get the actual GoodsID from GroupDetailList
                            await self.get_group_detail(group_auto_id)
                        else:
                            _LOGGER.warning("No inverter groups found in response")
                        return groups
                    else:
                        _LOGGER.error("Failed to get group list (HTTP %s)", response.status)
                        return []
                    
        except Exception as err:
            _LOGGER.error("Error getting group list: %s", err, exc_info=True)
            return []

    async def get_group_detail(self, group_auto_id: str) -> dict[str, Any]:
        """Get detailed group information including actual GoodsID."""
        if not self.token or not self.member_auto_id:
            if not await self.login():
                return {}
            
        try:
            session = await self._get_session()
            
            payload = signed_payload({
                "GroupAutoID": group_auto_id,
                "MemberAutoID": self.member_auto_id,
            })
            
            headers = {
                "Content-Type": "application/json",
                "authorization": self.token,
                "cookie": "timezone=Asia%2FKarachi"
            }
            
            async with asyncio.timeout(30):
                async with session.post(ENDPOINT_GROUP_DETAIL, json=payload, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        _LOGGER.debug("Group detail response received")
                        
                        inverters = data.get("AllInverterList", [])
                        if inverters and len(inverters) > 0:
                            # Get the actual GoodsID (serial number) from the first inverter
                            first_inverter = inverters[0]
                            self.goods_id = first_inverter.get("GoodsID")
                            _LOGGER.info("Found inverter in group detail")
                            return data
                        else:
                            _LOGGER.warning("No inverters found in group detail")
                            return {}
                    else:
                        _LOGGER.error("Failed to get group detail (HTTP %s)", response.status)
                        return {}
                    
        except Exception as err:
            _LOGGER.error("Error getting group detail: %s", err, exc_info=True)
            return {}

    async def get_inverter_data(self, goods_id: str = None) -> dict[str, Any]:
        """Get detailed inverter data."""
        if not self.token or not self.member_auto_id:
            if not await self.login():
                return {}
            
        # Get goods_id if not provided
        if goods_id is None:
            if self.goods_id is None:
                # Get the goods_id from group list first
                groups = await self.get_group_list()
                if not groups:
                    _LOGGER.error("No inverter groups found")
                    return {}
            goods_id = self.goods_id
            
        if goods_id is None:
            _LOGGER.error("No goods_id available - check if GroupDetailList is working")
            return {}
            
        try:
            session = await self._get_session()
            
            headers = {
                "Content-Type": "application/json",
                "authorization": self.token,
                "cookie": "timezone=Asia%2FKarachi"
            }
            
            _LOGGER.debug("Requesting inverter data")
            
            payload = signed_payload({
                "GoodsID": goods_id,
                "MemberAutoID": self.member_auto_id,
            })
            
            async with asyncio.timeout(30):
                async with session.post(ENDPOINT_INVERTER_DETAIL, json=payload, headers=headers) as response:
                    if response.status == 200:
                        response_text = await response.text()
                        _LOGGER.debug("Inverter detail response length: %d bytes", len(response_text))
                        
                        try:
                            data = await response.json() if response_text else {}
                            if data and len(data) > 5:  # Should have multiple keys
                                _LOGGER.info("Successfully retrieved inverter data with %d fields", len(data))
                                return data
                            else:
                                _LOGGER.warning("Received minimal inverter data (%d fields)", len(data) if data else 0)
                                return data  # Return it anyway, might have some data
                        except Exception as e:
                            _LOGGER.error("Failed to parse inverter data JSON: %s", e)
                            return {}
                    else:
                        _LOGGER.error("Failed to get inverter data (HTTP %s)", response.status)
                        return {}
                    
        except Exception as err:
            _LOGGER.error("Error getting inverter data: %s", err, exc_info=True)
            return {}

    async def test_connection(self) -> bool:
        """Test if we can authenticate with the API."""
        try:
            # Try to login
            if not await self.login():
                _LOGGER.error("Test connection failed: Login unsuccessful")
                return False
            
            _LOGGER.info("Cloud Inverter authentication succeeded")
            return True
            
        except Exception as err:
            _LOGGER.error("Connection test failed with exception: %s", err)
            return False
