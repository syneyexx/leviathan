from __future__ import annotations

import unittest

from claim_register import STALE, assess_verification_state


class ClaimTimezoneExpiryTests(unittest.TestCase):
    def test_positive_offset_expired_in_utc_is_stale(self) -> None:
        # 12:00+14:00 == 22:00Z on the previous day, so it is already expired
        # at 00:30Z even though its wall-clock hour is numerically later.
        result = assess_verification_state(
            {
                "provenance": "file:/primary",
                "source_kind": "primary",
                "supports": ["file:/primary", "file:/independent"],
                "valid_until": "2026-01-01T12:00:00+14:00",
            },
            now="2026-01-01T00:30:00Z",
        )
        self.assertEqual(result["verification_status"], STALE)

    def test_negative_offset_future_in_utc_is_not_stale(self) -> None:
        # 12:00-12:00 == 00:00Z on the next day, so it is still valid at
        # 23:30Z despite its wall-clock hour being numerically earlier.
        result = assess_verification_state(
            {
                "provenance": "file:/primary",
                "source_kind": "primary",
                "supports": ["file:/primary", "file:/independent"],
                "valid_until": "2026-01-01T12:00:00-12:00",
            },
            now="2026-01-01T23:30:00Z",
        )
        self.assertNotEqual(result["verification_status"], STALE)


if __name__ == "__main__":
    unittest.main()
