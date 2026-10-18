# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Photometric units for the renderer: real fixtures (lumens, kelvin, beam angle, dimmer setting), daylight (lux) and
cameras (EXIF exposure) to Blender/Cycles units, and back. No Blender import, so it is unit-tested and usable anywhere.

Conventions (measured in Cycles 4.5, see tests/test_photometry.py): a light's colour is normalised to luminance Y = 1
(linear Rec.709 / sRGB primaries, D65 white), and one Blender watt of such a light is 683 lumens (the photopic peak,
as in other physically based renderers). Cycles itself is plain radiometry: a point light of P W has intensity P/4π W/sr,
a spot light has the intensity of the point light of the same power (masked to its cone), an area light is Lambertian
(radiance P/(π·A)), a sun's strength is irradiance (W/m²), and a world or emission strength is radiance (W/m²/sr). So
scene-linear pixel values are luminance / 683 (cd/m²).

Usage: `uv run tools/photometry.py <kelvin>` prints the light colour, `... ev <t> <N> <ISO>` a photo's EV100 and the
render exposure that matches it.
"""

import math
import sys

LM_PER_W = 683.0  # lumens per Blender watt of a Y = 1 light (cd/m² per unit of scene-linear radiance)
MIDDLE_GREY = 0.18  # scene-linear value a camera puts the metered luminance at
METER_K = 12.5  # reflected-light meter calibration constant (ISO 2720), cd/m²
D65_K = 6504

# Assumptions used when the data doesn't say (every render lists the lights that used one, as ASSUMED lines).
DEFAULT_KELVIN = 2700  # typical warm-white household bulb
DEFAULT_BULB_LM = 800  # an A19 "60 W equivalent" bulb
DEFAULT_CAN = {"lumens": 700, "kelvin": 2700, "beam": 110}  # a 6-inch LED retrofit downlight (650-900 lm)
DEFAULT_FIRE = {"gas": {"lumens": 300, "kelvin": 1900}, "wood": {"lumens": 1000, "kelvin": 1900}}
DEFAULT_CANDLE = {"lumens": 12, "kelvin": 1850}  # one candela in every direction
OVERCAST_LUX = 10000  # horizontal illuminance of a CIE overcast sky, the usual daylight-design reference
GROUND_ALBEDO = 0.2

# A camera's white balance only partly neutralises a warm or cool cast (phones and eyes keep some of it, so lamplight
# still reads warm). Fraction of the way, in mired, from D65 to the light's colour temperature that the white
# balance goes: six iPhone night photos fitted with tools/light_match.py gave a median of 0.76 (0.62-0.84).
WB_ADAPTATION = 0.75

# The renders before photometric units (2026-10) used made-up watts. Builders still carry those numbers as weights;
# a lamp without `light` data gets lumens = legacy watts x the colour's luminance x this factor, anchored on the old
# shade lamp (55 W of the old warm colour) = an 800 lm bulb. Emission strengths in builders scale by LEGACY_EMISSION.
LEGACY_WARM = (1.0, 0.72, 0.45)
LEGACY_LM_PER_W = DEFAULT_BULB_LM / (55 * (0.2126 * LEGACY_WARM[0] + 0.7152 * LEGACY_WARM[1] + 0.0722 * LEGACY_WARM[2]))
LEGACY_EMISSION = LEGACY_LM_PER_W / LM_PER_W

_XYZ_TO_RGB = ((3.2404542, -1.5371385, -0.4985314), (-0.9692660, 1.8760108, 0.0415560), (0.0556434, -0.2040259, 1.0572252))
_RGB_TO_XYZ = ((0.4124564, 0.3575761, 0.1804375), (0.2126729, 0.7151522, 0.0721750), (0.0193339, 0.1191920, 0.9503041))


def luminance(rgb):
    """Y of a linear Rec.709 colour."""
    r, g, b = rgb[:3]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def planck_xy(kelvin):
    """CIE 1931 xy of a blackbody (Kim et al. 2002 cubic fit, 1667-25000 K)."""
    t = min(max(float(kelvin), 1667.0), 25000.0)
    if t <= 4000:
        x = -0.2661239e9 / t ** 3 - 0.2343589e6 / t ** 2 + 0.8776956e3 / t + 0.179910
    else:
        x = -3.0258469e9 / t ** 3 + 2.1070379e6 / t ** 2 + 0.2226347e3 / t + 0.240390
    if t <= 2222:
        y = -1.1063814 * x ** 3 - 1.34811020 * x ** 2 + 2.18555832 * x - 0.20219683
    elif t <= 4000:
        y = -0.9549476 * x ** 3 - 1.37418593 * x ** 2 + 2.09137015 * x - 0.16748867
    else:
        y = 3.0817580 * x ** 3 - 5.87338670 * x ** 2 + 3.75112997 * x - 0.37001483
    return x, y


def xy_to_rgb(x, y):
    """Linear Rec.709 colour of chromaticity xy, negatives clipped, normalised to Y = 1."""
    X, Y, Z = x / y, 1.0, (1 - x - y) / y
    rgb = [max(0.0, r[0] * X + r[1] * Y + r[2] * Z) for r in _XYZ_TO_RGB]
    lum = luminance(rgb)
    return tuple(c / lum for c in rgb)


def kelvin_rgb(kelvin):
    """Light colour of a colour temperature as linear Rec.709, luminance 1 (matches Blender's light temperature)."""
    return xy_to_rgb(*planck_xy(kelvin))


def rgb_xy(rgb):
    X, Y, Z = (sum(m * c for m, c in zip(row, rgb[:3])) for row in _RGB_TO_XYZ)
    s = X + Y + Z
    return (X / s, Y / s) if s > 0 else (0.3127, 0.3290)


def rgb_kelvin(rgb):
    """Correlated colour temperature of a linear Rec.709 colour (McCamy 1992; good for about 2000-12500 K)."""
    x, y = rgb_xy(rgb)
    n = (x - 0.3320) / (0.1858 - y)
    return 449 * n ** 3 + 3525 * n ** 2 + 6823.3 * n + 5520.33


def mired(kelvin):
    return 1e6 / kelvin


def watts(lumens):
    """Blender power (W) of a point or area light emitting `lumens` (colour normalised to Y = 1)."""
    return lumens / LM_PER_W


def cone_solid_angle(beam_deg):
    """Solid angle (sr) of a cone with full angle beam_deg."""
    return 2 * math.pi * (1 - math.cos(math.radians(min(beam_deg, 360.0)) / 2))


def spot_watts(lumens, beam_deg):
    """Blender power of a spot light that puts `lumens` into a cone of full angle beam_deg (a fixture's rated output
    is what leaves it, so all of it goes into the cone; Blender spot power is that of the equivalent point light)."""
    return watts(lumens) * 4 * math.pi / cone_solid_angle(beam_deg)


def emission_strength(cd_m2):
    """Emission (or world background) strength for a surface of luminance cd_m2 (colour normalised to Y = 1)."""
    return cd_m2 / LM_PER_W


def sun_strength(lux):
    """Blender sun strength (W/m², colour Y = 1) for a direct normal illuminance in lux."""
    return lux / LM_PER_W


def dimmer_output(setting, curve="square"):
    """Light output (0-1) at a dimmer setting (0-1). Most wall and plug-in dimmers follow roughly a square law
    (a 20% setting gives about 4% of the light); "linear" for drivers that don't; "log" for DALI-style logarithmic."""
    s = min(max(float(setting), 0.0), 1.0)
    if curve == "linear":
        return s
    if curve == "log":
        return 0.0 if s <= 0 else 10 ** (3 * (s - 1))  # 1/1000 at the bottom of the range, like DALI
    if curve == "square":
        return s * s
    raise ValueError(f"unknown dimCurve {curve!r} (square, linear, log)")


def dim_to_warm(setting, k_full, k_min):
    """Colour temperature of a dim-to-warm bulb at a dimmer setting: linear in mired from k_min (bottom) to k_full."""
    s = min(max(float(setting), 0.0), 1.0)
    return 1e6 / (mired(k_min) + (mired(k_full) - mired(k_min)) * s)


def ev100(exposure_time, f_number, iso):
    """Exposure value at ISO 100 of a photo (EXIF ExposureTime s, FNumber, ISOSpeedRatings)."""
    return math.log2(f_number ** 2 / exposure_time) - math.log2(iso / 100)


def metered_luminance(ev):
    """Scene luminance (cd/m²) a camera at EV100 `ev` renders as middle grey."""
    return METER_K * 2 ** ev / 100


def exposure_for_luminance(cd_m2, key=MIDDLE_GREY):
    """Blender view exposure (stops) that puts a luminance at `key` in scene-linear."""
    return math.log2(key * LM_PER_W / max(cd_m2, 1e-9))


def exposure_for_ev(ev):
    """Blender view exposure that matches a camera set to EV100 `ev` (e.g. read from a photo's EXIF)."""
    return exposure_for_luminance(metered_luminance(ev))


def auto_key(cd_m2):
    """Where a camera's auto exposure puts a scene's log-average luminance, like a phone: dim scenes stay darker
    than bright ones instead of being lifted to the same grey. Krawczyk et al. (2005) key-value curve, normalised so
    a typically lit interior (50 cd/m²) lands on middle grey."""
    def a(lum):
        return 1.03 - 2 / (2 + math.log10(lum + 1))

    return MIDDLE_GREY * max(a(max(cd_m2, 0.0)), 0.05) / a(50.0)


def auto_exposure(log_avg_cd_m2):
    """Exposure (stops) a phone-like camera picks for a scene whose log-average luminance is log_avg_cd_m2."""
    return exposure_for_luminance(log_avg_cd_m2, auto_key(log_avg_cd_m2))


def adapted_white_balance(light_kelvin, adaptation=WB_ADAPTATION):
    """White balance (K) a camera picks under light of light_kelvin: part of the way from D65 (see WB_ADAPTATION)."""
    m = mired(D65_K) + adaptation * (mired(light_kelvin) - mired(D65_K))
    return min(max(1e6 / m, 1900.0), 12000.0)


# ---------------------------------------------------------------- daylight


def solar_position(latitude, day_of_year, solar_hour):
    """Sun altitude and azimuth (degrees; azimuth clockwise from true north) at a latitude, day of the year and
    local solar time (12 = solar noon). Simple declination model, good to about a degree."""
    decl = math.radians(23.44) * math.sin(math.radians(360 / 365 * (day_of_year - 81)))
    lat, ha = math.radians(latitude), math.radians(15 * (solar_hour - 12))
    sin_alt = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(ha)
    alt = math.asin(max(-1.0, min(1.0, sin_alt)))
    cos_az = (math.sin(decl) - sin_alt * math.sin(lat)) / max(math.cos(alt) * math.cos(lat), 1e-9)
    az = math.degrees(math.acos(max(-1.0, min(1.0, cos_az))))
    return math.degrees(alt), (360 - az if ha > 0 else az)


def air_mass(alt_deg):
    """Relative optical air mass (Kasten and Young 1989)."""
    a = max(alt_deg, 0.0)
    return 1 / (math.sin(math.radians(a)) + 0.50572 * (a + 6.07995) ** -1.6364)


def clear_sky(alt_deg):
    """Clear sky (IES daylighting model): (direct normal illuminance of the sun, diffuse horizontal illuminance
    of the sky), lux."""
    if alt_deg <= 0:
        return 0.0, 0.0
    direct = 127500 * math.exp(-0.21 * air_mass(alt_deg))
    diffuse = 800 + 15500 * math.sin(math.radians(alt_deg)) ** 0.5
    return direct, diffuse


def overcast_sky(alt_deg=None):
    """Horizontal illuminance (lux) of an overcast sky: IES model at a sun altitude, else the design reference."""
    if alt_deg is None:
        return float(OVERCAST_LUX)
    return max(0.0, 300 + 21000 * math.sin(math.radians(alt_deg)))


def overcast_zenith(horizontal_lux):
    """Zenith luminance (cd/m²) of a CIE overcast sky, L(alt) = Lz (1 + 2 sin alt) / 3, with this horizontal
    illuminance (E = 7π Lz / 9)."""
    return 9 * horizontal_lux / (7 * math.pi)


def sun_kelvin(alt_deg):
    """Approximate colour temperature of direct sunlight: about 5500 K when high, redder within 20° of the horizon."""
    return 5500 if alt_deg >= 20 else 2500 + 3000 * max(alt_deg, 0) / 20


def plan_direction(bearing_deg, north_deg):
    """Unit (x, y) in room coordinates of a compass bearing, for a room whose +y axis points at compass bearing
    north_deg (0 = +y is true north, 90 = +y is east)."""
    b = math.radians(bearing_deg - north_deg)
    return math.sin(b), math.cos(b)


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "ev":
        ev = ev100(float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]))
        print(f"EV100 {ev:.2f}: metered luminance {metered_luminance(ev):.2f} cd/m², render exposure {exposure_for_ev(ev):.2f}")
    elif len(sys.argv) == 2:
        k = float(sys.argv[1])
        print(f"{k:.0f} K: linear RGB {tuple(round(c, 4) for c in kelvin_rgb(k))}, white balance {adapted_white_balance(k):.0f} K")
    else:
        print(__doc__)
