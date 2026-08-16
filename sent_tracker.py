"""
Η "μνήμη ήδη-σταλμένων" -- ξεχωριστή ανά κανάλι, ώστε να μην ξαναστέλνουμε
το ίδιο market για τον ίδιο αγώνα ξανά και ξανά μέσα στο ίδιο παράθυρο ελέγχου.

Prematch: καθαρίζει μόλις περάσει η ώρα έναρξης του αγώνα.
Live: καθαρίζει μόλις ο αγώνας τελειώσει (δεν εμφανίζεται πια στο live feed).
"""

import time

# {channel_key: {(fixture_id, market): timestamp}}
_sent = {}


def already_sent(channel_key, fixture_id, market):
    channel_memory = _sent.get(channel_key, {})
    return (fixture_id, market) in channel_memory


def mark_sent(channel_key, fixture_id, market):
    _sent.setdefault(channel_key, {})[(fixture_id, market)] = time.time()


def clear_expired_prematch(channel_key, still_valid_fixture_ids):
    """Αφαιρεί από τη μνήμη ό,τι fixture_id δεν είναι πια στο τρέχον παράθυρο."""
    channel_memory = _sent.get(channel_key, {})
    to_delete = [key for key in channel_memory if key[0] not in still_valid_fixture_ids]
    for key in to_delete:
        del channel_memory[key]


def clear_finished_live(channel_key, still_live_fixture_ids):
    """Αφαιρεί από τη μνήμη ό,τι fixture_id δεν είναι πια live."""
    channel_memory = _sent.get(channel_key, {})
    to_delete = [key for key in channel_memory if key[0] not in still_live_fixture_ids]
    for key in to_delete:
        del channel_memory[key]
