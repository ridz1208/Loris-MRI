from decimal import Decimal

import pytest

import lib.db.models.hed_schema  # type: ignore  # ruff:ignore[unused-import]
from lib.db.models.physio_event_file import DbPhysioEventFile
from lib.db.models.physio_file import DbPhysioFile
from lib.env import Env
from lib.physio.events import insert_physio_task_event


@pytest.mark.parametrize('response_time', [None, Decimal('0.375')])
def test_task_event_response_time_round_trip(env: Env, response_time: Decimal | None):
    event = insert_physio_task_event(
        env=env,
        physio_file=DbPhysioFile(id=1),
        events_file=DbPhysioEventFile(id=1),
        onset=Decimal('1.25'),
        duration=Decimal('0.5'),
        event_code=None,
        event_value=None,
        event_sample=42,
        event_type=None,
        trial_type=None,
        response_time=response_time,
    )

    env.db.expire(event)

    assert event.response_time == response_time
    assert event.event_sample == 42
