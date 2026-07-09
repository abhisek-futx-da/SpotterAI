"""Real carrier verification via the FMCSA QCMobile API (US DOT, free, requires
a webKey from https://mobile.fmcsa.dot.gov/QCDevsite/ -- registration needs a
Login.gov account). This is the authoritative US government source for motor
carrier authority/safety status; there is no better or more "real" source for
this data. Unlike rate_intelligence.py, this feature has no estimated fallback
-- if it can't reach FMCSA or the key isn't configured, it says so plainly
rather than guessing."""
import json
import re
import urllib.error
import urllib.request
from os import environ


class CarrierVerificationService:

    BASE_URL = "https://mobile.fmcsa.dot.gov/qc/services/carriers"

    def verify_carrier(self, dot_number: str) -> dict:
        dot_number = re.sub(r"\D", "", dot_number or "")
        if not dot_number:
            return self._result(found=False, message="Enter a valid DOT number (digits only).")
        # DOT authority/safety records change rarely — cache 10 min per DOT.
        from .ttl_cache import cached_call
        return cached_call(f"fmcsa:{dot_number}", 600, lambda: self._verify_live(dot_number))

    def _verify_live(self, dot_number: str) -> dict:
        web_key = environ.get("FMCSA_WEBKEY", "")
        if not web_key:
            return self._result(
                found=False,
                message=(
                    "Carrier verification is not configured. Set FMCSA_WEBKEY "
                    "(free, register at https://mobile.fmcsa.dot.gov/QCDevsite/) "
                    "to enable real DOT/MC lookups."
                ),
                data_source="unavailable",
            )

        url = f"{self.BASE_URL}/{dot_number}?webKey={web_key}"
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return self._result(
                found=False,
                message="FMCSA lookup failed (network or service error). Try again shortly.",
                data_source="unavailable",
            )

        content = payload.get("content") if isinstance(payload, dict) else None
        carrier = (content or {}).get("carrier") if isinstance(content, dict) else None
        if not carrier:
            return self._result(
                found=False,
                message=f"No carrier found for DOT {dot_number} in the FMCSA database.",
                data_source="real",
            )

        allowed_to_operate = self._truthy(carrier.get("allowedToOperate"))
        safety_rating = carrier.get("safetyRating") or "Not rated"

        return self._result(
            found=True,
            data_source="real",
            dot_number=dot_number,
            legal_name=carrier.get("legalName"),
            dba_name=carrier.get("dbaName"),
            allowed_to_operate=allowed_to_operate,
            safety_rating=safety_rating,
            power_units=carrier.get("totalPowerUnits"),
            drivers=carrier.get("totalDrivers"),
            carrier_operation=(carrier.get("carrierOperation") or {}).get("carrierOperationDesc"),
            message=(
                "Authorized to operate." if allowed_to_operate
                else "NOT currently authorized to operate -- verify before booking."
            ),
        )

    @staticmethod
    def _truthy(value) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().upper() in ("Y", "YES", "TRUE", "1")

    @staticmethod
    def _result(found: bool, message: str, data_source: str = "real", **fields) -> dict:
        return {"found": found, "message": message, "data_source": data_source, **fields}
