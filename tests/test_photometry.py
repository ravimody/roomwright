"""Photometric conversions (tools/photometry.py): no Blender."""

import math

import pytest

import photometry as ph


def test_kelvin_rgb_matches_blender():
    """Same light colours as Blender 4.5's own light temperature (Light.temperature_color), within 1%."""
    blender = {1900: (2.6386, 0.6136, 0.0), 2700: (1.9351, 0.8035, 0.1917), 4000: (1.4141, 0.9236, 0.5337), 6500: (1.0425, 0.9841, 1.0353)}
    for k, want in blender.items():
        got = ph.kelvin_rgb(k)
        assert ph.luminance(got) == pytest.approx(1.0, abs=1e-6)
        for g, w in zip(got, want):
            assert g == pytest.approx(w, abs=0.02 * max(w, 1.0)), (k, got, want)


@pytest.mark.parametrize("k", [1900, 2200, 2700, 3000, 4000, 5000, 6500, 9000])
def test_kelvin_round_trip(k):
    assert ph.rgb_kelvin(ph.kelvin_rgb(k)) == pytest.approx(k, rel=0.03)


def test_lumens_and_beams():
    assert ph.watts(683) == pytest.approx(1.0)
    # a 180-degree cone is a hemisphere: the equivalent point light emits twice the fixture's lumens
    assert ph.spot_watts(683, 180) == pytest.approx(2.0)
    assert ph.cone_solid_angle(360) == pytest.approx(4 * math.pi)
    # narrower beams concentrate the same lumens: intensity (point-equivalent power) goes up
    assert ph.spot_watts(700, 60) > ph.spot_watts(700, 110) > ph.watts(700)
    assert ph.emission_strength(683) == pytest.approx(1.0)
    assert ph.sun_strength(100000) == pytest.approx(146.4, rel=1e-3)


def test_dimmer_curves():
    assert ph.dimmer_output(0.2) == pytest.approx(0.04)
    assert ph.dimmer_output(0.2, "linear") == pytest.approx(0.2)
    assert ph.dimmer_output(1.0, "log") == pytest.approx(1.0)
    assert ph.dimmer_output(0.0, "log") == 0.0
    assert ph.dimmer_output(1.5) == 1.0
    with pytest.raises(ValueError):
        ph.dimmer_output(0.5, "cubic")
    assert ph.dim_to_warm(1.0, 2700, 2200) == pytest.approx(2700)
    assert ph.dim_to_warm(0.0, 2700, 2200) == pytest.approx(2200)
    assert 2200 < ph.dim_to_warm(0.5, 2700, 2200) < 2700


def test_exif_exposure():
    # sunny-16: f/16, 1/100 s, ISO 100 is about EV 14.6
    assert ph.ev100(1 / 100, 16, 100) == pytest.approx(14.64, abs=0.01)
    assert ph.ev100(1 / 50, 2.8, 400) == pytest.approx(ph.ev100(1 / 50, 2.8, 100) - 2)
    # the metered luminance lands on middle grey after the exposure
    ev = 4.0
    lum = ph.metered_luminance(ev)
    assert lum == pytest.approx(12.5 * 16 / 100)
    assert lum / ph.LM_PER_W * 2 ** ph.exposure_for_ev(ev) == pytest.approx(ph.MIDDLE_GREY)


def test_auto_exposure_keeps_dim_scenes_darker():
    assert ph.auto_key(50) == pytest.approx(ph.MIDDLE_GREY)
    assert ph.auto_key(1) < ph.auto_key(10) < ph.auto_key(50) < ph.auto_key(500)
    # a 100x dimmer scene gets more exposure, but less than the 6.6 stops that would make it look the same
    gain = ph.auto_exposure(0.5) - ph.auto_exposure(50)
    assert 3 < gain < math.log2(100)


def test_white_balance_keeps_some_warmth():
    assert ph.adapted_white_balance(6504) == pytest.approx(6504, rel=1e-3)
    wb = ph.adapted_white_balance(2700)
    assert 2700 < wb < 6504


def test_sun_and_sky():
    alt, az = ph.solar_position(40, 172, 12)  # June solstice, solar noon, 40 N
    assert alt == pytest.approx(73.4, abs=0.5) and az == pytest.approx(180, abs=0.5)
    alt, az = ph.solar_position(40, 80, 9)
    assert 20 < alt < 45 and 90 < az < 180  # morning sun in the south-east
    direct, diffuse = ph.clear_sky(60)
    assert 80000 < direct < 110000 and 10000 < diffuse < 20000
    assert ph.clear_sky(-5) == (0.0, 0.0)
    # CIE overcast: integrating L(alt) = Lz (1 + 2 sin alt) / 3 over the sky gives the horizontal illuminance back
    lz = ph.overcast_zenith(10000)
    n = 400
    e = sum(lz * (1 + 2 * math.sin(a)) / 3 * math.sin(a) * math.cos(a) * 2 * math.pi * (math.pi / 2 / n)
            for a in ((i + 0.5) * math.pi / 2 / n for i in range(n)))
    assert e == pytest.approx(10000, rel=1e-3)
    x, y = ph.plan_direction(90, 0)  # east, room +y = north
    assert (x, y) == pytest.approx((1, 0), abs=1e-9)
    x, y = ph.plan_direction(0, 90)  # north, room +y = east: north is -x
    assert (x, y) == pytest.approx((-1, 0), abs=1e-9)


def test_old_lighting_keys_are_errors():
    """Keys the renderer no longer reads must not pass silently (the schemas allow extra keys)."""
    import validate_room

    rep = validate_room.Report()
    room = {"lights": {"canEnergy": {"workout": 75}}, "daylight": {"ambient": 1.4}, "exposure": {"day": 1.5},
            "fixtures": [{"id": "fp", "fireWatts": 50}, {"id": "tv", "screen": {}}],
            "scenes": {"a": {"uplights": True, "cans": 6.0, "screens": ["tv", "nope"]}}}
    validate_room.check_lighting(room, "room.json", rep)
    text = "\n".join(rep.errors)
    for bit in ("canEnergy", "ambient", "exposure", "fireWatts", "uplights", "0-1", "'nope'"):
        assert bit in text, bit
    assert "'tv'" not in text


def test_legacy_anchor():
    """The old renders' 55 W warm shade-lamp bulb is an 800 lm bulb."""
    assert 55 * ph.luminance(ph.LEGACY_WARM) * ph.LEGACY_LM_PER_W == pytest.approx(800)
