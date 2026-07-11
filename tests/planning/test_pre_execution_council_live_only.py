from agents.planning.pre_execution_council import CouncilConfig, CouncilRunner, LiveLocalCouncilSeat


def test_live_only_council_builds_only_requested_local_seat():
    runner = CouncilRunner(CouncilConfig(enabled=True, mock_seats_enabled=False, live_local_enabled=True, local_model="test"))
    seats = runner._build_seats()
    assert len(seats) == 1
    assert isinstance(seats[0], LiveLocalCouncilSeat)
