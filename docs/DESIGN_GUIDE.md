# Design guide

Widely shared interior-design practice, collected for the people and agents who use roomwright. **It is guidance, not rules.** The tools measure and render whatever you design; this page only helps the conversation.

## How to use it

- **The people come first.** How they live, their culture, style, budget, who's in the house (children, pets, older relatives, guests, people with disabilities) and what they already own outrank anything here. A household's `HOUSEHOLD.md` and a room's `style` and `sourcing` override this guide.
- **Ask before applying a guideline.** Explain it as a starting point ("many people find 35–45 cm between a sofa and a coffee table comfortable"), then let the person decide. Floor seating, a deliberately tight nook, a maximalist room and a bright, evenly lit room all break somebody's "rules".
- **Separate taste from evidence.** Safety, accessibility and the research on sleep and light are evidence; most of the rest (colour, warm or cool light, how full a room should be, rug and art conventions) is taste and local habit. Present taste as options, never as what "people" want.
- **Offer range.** Next to the safe default, show at least one option that takes a creative risk in the person's own style. Never steer every room towards one look or one culture's norms.
- **Numbers are typical, not universal.** Figures are metric first, imperial in brackets, with the region they come from. Building and accessibility codes set minimums for the buildings they cover; most private homes aren't bound by them, but they are the best-researched numbers there are. Look up the person's own national code: examples are the US ADA and Fair Housing guidelines, UK Approved Document M, Australia's AS 1428.1, Japan's barrier-free housing grades, India's Harmonised Guidelines for Universal Accessibility, China's GB 55019, South Africa's SANS 10400-S and Brazil's ABNT NBR 9050. Local codes win where they apply.
- Use the engine to check what's measurable. Path widths and seating distances: `flow-plan`. Overlaps, door swings, keep-clear zones: `check-layout`. Light and colour as the room really is: photoreal renders matched to photos.

**Sources and evidence.** Each number is backed by at least two independent sources where possible, preferring standards and codes, government agencies, professional bodies (such as NKBA) and peer-reviewed research, then design textbooks. Some everyday conventions (rug sizes, art height, curtain height, sofa-to-table distance) come from no standard at all: they are trade conventions, labelled as such. Evidence is weakest for colour and mood (§6), colour-temperature preference and exact light levels at home (§5): treat those as ranges to discuss, not targets.

## 1. Start with how the room is used

Before proposing anything, find out:
- What happens in the room, by whom, and when: mornings vs. evenings, everyday vs. gatherings. How many people at the busiest time (a festival, a family gathering, a party), and which spaces are for guests and which for family.
- Who needs what:
  - children and pets (durable, washable, nothing precious or dangerous within reach);
  - people who use a wheelchair, walker or cane, or have low vision or hearing, now or likely later (§10);
  - left- and right-handed habits; tall and short people.
- Who decides, and whose say wins in which room (in multigenerational homes this varies).
- What stays (heirlooms, built-ins, things they love) and what they want gone.
- Their style in their own words, plus a few reference images. Ask what they *don't* like; it's often clearer. Ask how full they like a room: some love space around each piece, others love collections and pattern.
- Budget, timeline, and how things will be sourced: new, secondhand, antique, made by a local carpenter or maker, or rearranging what they have.
- Renting or owning: renters may not be allowed to paint, drill, rewire or hang heavy things.
- Climate and comfort: hot or cold seasons, humidity, how the room feels by day and at night, heating or cooling (fans, air conditioning, radiators, stoves), and what can be heard from outside.
- Power: how reliable it is, and what backup exists (inverter, battery, generator).
- Culture and habits: shoes off or on, floor seating, how guests are received, how meals are eaten, prayer or meditation, a shrine or altar. Many layouts that read as "wrong" in one tradition are standard in another.
- **Placement systems and sacred spaces** (Vastu, feng shui, a prayer direction such as the qibla, a pooja room or home altar, a butsudan): treat them as the person's own constraints. Record them in `HOUSEHOLD.md` or the room's README, tied to true north (`site.northDeg`; the room's "north wall" is only a plan label; how to measure it: [COOKBOOK, Accuracy and directions](../COOKBOOK.md#accuracy-and-directions)); a zone to keep clear can also be a `keepClear` rule. Never judge, explain away or apply them unasked.

## 2. Principles of design

The classic principles are a vocabulary for explaining *why* something feels right or off, not a checklist. Design textbooks list balance, proportion and scale, rhythm, emphasis and harmony (unity); many add contrast and variety.

- **Balance:** visual weight arranged so the room feels stable: symmetrical (formal, mirrored), asymmetrical (unlike things weighed against each other) or radial (around a centre, such as seats round a table). Dark, large, busy and dense objects weigh more.
- **Proportion and scale:** proportion is how the parts of a thing relate to each other; scale is how a thing relates to the room and to people. Check scale in a render from where people actually stand, sit or sit on the floor, not only in plan.
- **Rhythm:** repetition and progression of colour, shape, texture or line that leads the eye.
- **Emphasis (focal point):** what draws the eye first: a view, a fireplace, a TV or media wall, artwork, a bed wall, a tokonoma alcove, a home altar, a chandelier, a striking piece. Competing focal points feel restless; none at all feels flat. Some traditions place the focal point by custom (where the eldest or a guest of honour sits); ask.
- **Harmony and unity:** a shared thread of style, palette or material, so different pieces feel like one room. Things should complement each other; they don't have to match.
- **Contrast and variety:** light against dark, smooth against rough, old against new, straight against curved.

*When to break it:* intentionally. A clash of eras, maximal pattern or one unexpected colour is often what makes a room personal.

Sources: F. D. K. Ching and C. Binggeli, *Interior Design Illustrated* (Wiley), ch. on design principles; [Ohio University, ART 2650: Some Principles of Design](https://people.ohio.edu/ziff/ART%202650/Some%20Principles%20of%20Design.pdf).

## 3. Space planning and circulation

Plan the paths first, then the furniture. Measure clear widths at the narrowest point and at floor level (`flow-plan` does this).

| What | Typical guideline | Where it comes from |
|---|---|---|
| Main walkway inside a home | ≥ 900–915 mm (36 in); 1050 mm for wheelchair housing | NKBA; US Fair Housing; UK M4(2)/M4(3) |
| Secondary path (to a window, beside a bed) | ≥ 750 mm (30 in) | UK M4(2) |
| Door, clear opening | 800–815 mm (32 in); 850–865 mm (34 in) for wheelchair access | NKBA; US Fair Housing; UK M4(2)/M4(3); AS 1428.1 |
| Wheelchair turning | 1500 mm (60 in) circle, or a 1700 × 1400 mm ellipse in living rooms | ADA 304.3.1; UK M4(3); Lifetime Homes |
| Kitchen work aisle | ≥ 1067 mm (42 in) one cook, ≥ 1219 mm (48 in) several | NKBA; UK M4(2) (1200 mm) |
| Kitchen work triangle (sink, hob, fridge) | each leg 1.2–2.7 m (4–9 ft), total ≤ 7.9 m (26 ft); no main walkway through it | NKBA |
| Table or counter edge to the wall behind diners | 813 mm (32 in) no traffic; 914 mm (36 in) to edge past; 1118 mm (44 in) to walk past; 1524 mm (60 in) for a wheelchair | NKBA; European references |
| Beside a bed | 750 mm (30 in) on both sides and the foot of a main double bed; 1000 mm (39 in) for wheelchair users | UK M4(2)/M4(3); design references |
| In front of a wardrobe or chest of drawers | about 0.9–1.0 m (36–39 in), so drawers and doors open with someone standing there | UK M4(3); design references |
| Sofa to coffee table | 35–45 cm (14–18 in) | Trade convention (no standard) |
| Conversation group | facing seats within about 2.4 m (8 ft) | Hall's "social distance" |
| TV viewing distance (16:9) | a 30–40° field of view: distance ≈ diagonal ÷ 0.6 (30°) to ÷ 0.84 (40°); a 165 cm (65 in) screen gives about 2.0–2.75 m (6.5–9 ft) | SMPTE EG-18; THX |

Notes on the table:
- **Regional widths.** UK M4(2) asks halls of at least 900 mm and a 750 mm route from every bedroom door to the window; M4(2) door widths run 750–800 mm depending on the hall. Homes built on Japan's 910 mm module often have about 780 mm clear, and its barrier-free grades ask 780–850 mm. Where two walkways meet at a right angle, NKBA suggests 1067 mm (42 in) for one of them. 610 mm (24 in) lets one person pass sideways.
- **Kitchens and dining.** UK M4(2) asks 1200 mm clear in front of and between kitchen units. The work triangle is a starting point for one-cook kitchens; zones suit islands and several cooks better. European references give a similar 750 mm minimum behind diners, 900–1000 mm where people pass.
- **Beds and conversation.** Design references give 610–910 mm (24–36 in) beside a bed. Hall's "social distance" for conversation among acquaintances is about 1.2–3.7 m (4–12 ft); comfortable distances vary by culture.
- **Sofa to table** is close enough to reach from the seat; wider with deep or reclining seats and small children.
- **TV distance:** SMPTE EG-18 gives a 30° minimum (withdrawn in 2003, still the common reference); THX suggests 36–40°.
- Keep door swings, drawer pulls, chair pull-back and the reach into wardrobes clear: these are the clashes people notice first (doors and `keepClear` rules in `room.json` let `check-layout` find them).
- **Arrangements are cultural.** Floating furniture in the middle of the room, seating along the walls (a majlis, a diwan, floor cushions) and floor-level living around a low table are all sound layouts; perimeter seating serves large gatherings well. Choose with the person, then check paths for the busiest occasion, not only the everyday one.
- Tape the footprint of a big new piece on the floor before buying. A render shows the look; tape shows the feel.

*When to break it:* small homes, floor-seating households, cosy nooks and rooms used by one person can run tighter. Say what's being traded.

Sources: [NKBA Kitchen Planning Guidelines with Access Standards (PDF)](https://kb.nkba.org/uploads/2022/05/Kitchen-Planning-Guidelines.pdf); [HUD Fair Housing Act Design Manual, ch. 4 (PDF)](https://www.huduser.gov/publications/pdf/fairhousing/fairch4.pdf); [UK Approved Document M, vol. 1: Dwellings (PDF)](https://assets.publishing.service.gov.uk/media/5a7f8a82ed915d74e622b17b/BR_PDF_AD_M1_2015_with_2016_amendments_V3.pdf); [Lifetime Homes: internal doorways and hallways](https://cae.org.uk/our-services/housing-services/lifetime-homes/6-internal-doorways-and-hallways/); [2010 ADA Standards, ch. 3](https://www.access-board.gov/ada/chapter/ch03/); [AS 1428.1 spatial dimensions (summary)](https://criterionindustries.com.au/blogs/blog/understanding-disability-access-spatial-dimensions); [Oita Prefecture: barrier-free housing grades (PDF, Japanese)](https://www.pref.oita.jp/uploaded/attachment/2161012.pdf); [KAKEN: wheelchair passage widths in homes](https://kaken.nii.ac.jp/grant/KAKENHI-PROJECT-08555148); [Proxemics (CUNY, after E. T. Hall, *The Hidden Dimension*)](https://openlab.citytech.cuny.edu/arch3512f2023/files/2022/11/Proxemics.pdf); [SMPTE EG-18 (PDF)](https://pub.smpte.org/doc/eg18/19940325-pub/eg0018-1994_withdrawn2003.pdf); [RTINGS: TV size to distance](https://rtings.com/tv/learn/size-to-distance-relationship).

## 4. Sizes that fit bodies

| What | Typical | Note |
|---|---|---|
| Dining table height | 71–76 cm (28–30 in) | Seats 43–48 cm (17–19 in), leaving 25–30 cm (10–12 in) from seat to tabletop |
| Width per diner | 60 cm (24 in) minimum; 66–76 cm (26–30 in) comfortable | NKBA (24 in of knee space per diner); European references ~60 cm, 70 cm for comfort |
| Low table for floor seating | about 15–40 cm high; about 30–33 cm is common today | Japanese chabudai were 15–30 cm; heated kotatsu tables run about 40 cm. Check with the people who will sit at it. |
| Knee space at a counter | 610 mm (24 in) wide; 457 / 381 / 305 mm (18 / 15 / 12 in) deep at 762 / 914 / 1067 mm (30 / 36 / 42 in) heights | NKBA |
| Desk and screen | Work surface at about seated elbow height; leg room 50–72 cm (20–28 in) high; screen 50–100 cm (20–40 in) away, its top at or slightly below eye level | OSHA computer workstation guidance; adjustability beats any single number |
| Switches, sockets, things used daily | 380–1220 mm (15–48 in) above the floor (US); 450–1200 mm (UK) | ADA forward reach (308.2.1); UK M4(2). Suits children and older adults too. |

Bed and mattress sizes differ by country (a "double", "queen" or "king" is not the same size everywhere): model from the actual mattress dimensions.

Sources: [NKBA (PDF)](https://kb.nkba.org/uploads/2022/05/Kitchen-Planning-Guidelines.pdf); J. Panero and M. Zelnik, *Human Dimension & Interior Space* (Watson-Guptill) and E. Neufert, *Architects' Data* (Wiley), the standard anthropometric references; [OSHA eTool: monitors](https://www.osha.gov/etools/computer-workstations/components/monitors) and [desks](https://www.osha.gov/etools/computer-workstations/components/desks); [Purdue: computer workstation ergonomics](https://www.purdue.edu/ehps/rem/laboratory/personal/ergo.html); [ADA ch. 3](https://www.access-board.gov/ada/chapter/ch03/); [UK Approved Document M, vol. 1](https://assets.publishing.service.gov.uk/media/5a7f8a82ed915d74e622b17b/BR_PDF_AD_M1_2015_with_2016_amendments_V3.pdf); [Wikipedia: chabudai](https://en.wikipedia.org/wiki/Chabudai).

## 5. Lighting

Light changes a room more than almost anything else. It also renders faithfully: model the real fixtures and check the result against photos (see COOKBOOK).

- **Start from how the room is lit now.** Many homes are lit by one main ceiling light (a pendant, chandelier, flush or panel light, tube or batten, a fan light) or by recessed downlights; others mostly by lamps. All are valid. Ask what the person likes about today's light and what bothers them.
- **Layers are an option.** Ambient (general light), task (where the work happens) and accent (art, texture, a plant) let one room be set for different moments. One bright, even overhead light is simpler, cheaper and the norm in many homes; offer layers where the person wants variety, don't assume them. One fixture can play different roles: a sconce is ambient in a hall and task light by a bed.
- **How much light.** Published values for homes differ between sources and countries (IES-based tables in North America, China's GB/T 50034, Japan's JIS Z 9110), and none is a legal requirement in homes. Use these ranges as a sanity check:

  | Activity | Typical illuminance |
  |---|---|
  | Living rooms, bedrooms, dining (ambient) | ~100–300 lx (10–30 fc) |
  | Halls and stairs | ~50–100 lx (5–10 fc) |
  | General kitchen | ~200–500 lx (20–50 fc) |
  | Reading, desk work, food prep | ~300–1000 lx (30–100 fc); EN 12464-1 asks 500 lx for reading and writing at work |

- **Daylight.** A useful benchmark from the UK national annex to EN 17037: a daylight median of 100 lx in bedrooms, 150 lx in living rooms and 200 lx in kitchens, over half the room for half the daylight hours. Don't block windows with furniture; in hot, sunny climates, daylight is balanced against heat and glare (§8), not maximised.
- **Colour temperature is preference.** People, cultures and climates differ: warm white (2700–3000 K) is the common choice in many North American and European homes, while neutral to cool white (4000–6500 K) is widely used at home in much of Asia and elsewhere. Lab studies find preferences shift by region and even with room temperature (warmer light preferred in cool rooms, cooler light in hot ones). Ask; record the answer in `HOUSEHOLD.md`. Some people dislike mixed colour temperatures in one view and others enjoy a warm lamp under a cool ceiling light: ask.
- **Colour rendering** is a quality floor: the EU requires CRI ≥ 80 for most light sources sold since 2021, and California's energy code asks ≥ 90 for qualifying home LED lighting. Use 90+ where colours, skin and food matter.
- **Daytime, evening and sleep (evidence).** A 2022 expert consensus (Brown et al., *PLOS Biology*), followed by the CIE's 2024 position statement, recommends: by day, plenty of light at the eye (at least 250 lx melanopic EDI; daylight is the easy way); from about three hours before bed, at most 10 lx melanopic EDI at the eye; during sleep, at most 1 lx. Any source can meet the evening limit when dimmed: a ceiling light's dim, warm or night setting works as well as lamps (with 2700 K light, 10 lx melanopic EDI is roughly 20–25 lx at the eye; cooler light reaches it sooner). The evidence is strongest for melatonin and alertness in healthy adults, and sensitivity varies; offer it once as a health note and let the person decide.
- **Older adults and low vision need more light, not less.** The Lighting Research Center suggests at least 300 lx ambient and 1000 lx on fine tasks for older adults, even levels between rooms and contrast at steps and edges (IES RP-28). Reconcile this with the evening guidance by keeping routes, stairs and tasks well lit with shielded, low-glare sources, cutting the light that reaches the eyes rather than the light on the floor, and adding night lights on the route to the bathroom.
- **Glare.** Shield bare bulbs and LED panels from normal sightlines (shades, diffusers, baffles, deep trims); prefer wide, diffuse light for general lighting; watch screens and glossy surfaces opposite bright sources.
- **Controls.** Many homes have only on/off switches, fan regulators, or ceiling lights dimmed by remote or app; wall and plug-in dimmers are common in some countries, rare in others. Use dimmable bulbs only on dimmers that match them, and don't put smart bulbs or lamps with built-in electronics behind a dimmer. Check the home's mains voltage and lamp base (E26, E27, B22, GU10…) before recommending bulbs.
- **When the power goes out.** Where outages are common, plan light for them: which lights run on the inverter or battery, rechargeable lamps and lanterns where people need them (stairs, the bathroom route, the kitchen), and efficient LEDs to stretch battery time. Flames used as backup light follow §11.

Sources: [Archtoolbox: recommended lighting levels (IES-based)](https://www.archtoolbox.com/recommended-lighting-levels/); [Penn State EGEE 102: how much lighting is needed](https://courses.ems.psu.edu/egee102/node/2363); [EN 12464-1 values (Signify code finder)](https://www.performanceinlighting.com/ww/en/en-12464-1); [GB/T 50034-2024 (catalogue entry)](https://www.chinesestandard.net/Related.aspx/GBT50034-2024); [Mitsubishi Electric: home lighting and JIS Z 9110 §5.10 (Japanese)](https://www.mitsubishielectric.co.jp/ldg/ja/lighting/products/fixture/ceiling/index.html); [LRC / AARP: lighting principles for older adults (archived)](https://web.archive.org/web/2022/https://www.lrc.rpi.edu/programs/lightHealth/AARP/designers/lightingOlderAdults/lightingPrinciples.asp); [EN 17037 UK annex for homes (Hoare Lea)](https://hoarelea.com/2022/09/09/a-step-forward-for-daylight-in-homes/) and [a council daylight assessment applying it](https://camdocs.camden.gov.uk/CMWebDrawer/Record/10859083/file/document); [Regional culture preferences to LED light colour (study abstract)](https://www.researchgate.net/publication/315472177_Regional_Culture_Preferences_to_LED_Light_Color_Rendering); [Influence of air temperature on preferred colour temperature (study abstract)](https://www.researchgate.net/publication/250057978_Influence_of_Air_Temperature_on_Preference_for_Color_Temperature_of_General_Lighting_in_the_Room); [EU Regulation 2019/2020 (ecodesign for light sources)](https://eur-lex.europa.eu/eli/reg/2019/2020); [California Title 24 JA8](https://energycodeace.com/site/custom/public/reference-ace-2013/Documents/appendixja8qualificationrequirementsforresidentialluminairesusin.htm); [Brown et al. 2022, PLOS Biology](https://pmc.ncbi.nlm.nih.gov/articles/PMC8929548/); [CIE: Recommending proper light at the proper time, 3rd ed. (2024)](https://cie.co.at/news/cie-releases-new-edition-its-position-statement-integrative-lighting); [Cooper Lighting: layering light](https://www.cooperlighting.com/global/resources/the-lighting-resource/residential-contractors-guide-to-layering-light).

## 6. Colour and materials

- **Value before hue.** How light or dark things are relative to each other sets a room's mood and legibility more than hue. Paint cards give it as light reflectance value (LRV, 0–100). For people with low vision, UK accessibility guidance asks for a 30-point LRV difference between things that must be told apart (a door and its wall, a step edge) and 20 points for large areas such as walls against floors.
- **Undertones decide close calls.** Two colours with similar LRV differ by undertone (warm, cool, green, pink). Compare samples against the room's fixed elements: floor, trim, stone, tile, big upholstery.
- **Test in the room's own light.** Paint or pin large samples (about 25 cm, 10 in, square or bigger) on more than one wall and look at them in the morning, at midday, under the room's own lights at night and on an overcast day: window orientation and the colour of the bulbs shift colour a lot. A render matched to the room's photos helps narrow choices; it doesn't replace a sample on the wall.
- **Bold and quiet are equally valid.** Saturated walls, colour drenching (walls, trim and ceiling in one colour), strong pattern and many colours together work as well as neutral palettes when they're chosen on purpose. Strong colours shift more under different light, so test them in the room.
- **Colour and mood: be modest.** Reviews find the research on colour and feelings thin and inconsistent; "blue calms, red excites" is folklore, and colour meanings differ between cultures. Go by the person's own reactions to samples.
- **Proportions.** 60-30-10 (dominant, secondary, accent) is one way to distribute colour: a convention, not a finding.
- **Sheen and wear.** Flatter finishes hide wall flaws; more sheen cleans better. Busy, child and pet areas favour washable paint and performance fabrics; humid rooms favour mould-resistant finishes and fabrics that dry quickly (§8).
- **Indoor air.** Prefer low- or zero-VOC paints and finishes; the US EPA advises extra ventilation during painting and for two to three days after.

Sources: [Wikipedia: light reflectance value (BS 8300 thresholds)](https://en.wikipedia.org/wiki/Light_reflectance_value); [ORS: visual contrast and Part M](https://ors.ie/visual-contrasts-and-tgd-part-m-compliance/); [Elliot 2015, Color and psychological functioning (Frontiers in Psychology)](https://www.frontiersin.org/articles/10.3389/fpsyg.2015.00368/full); [Jonauskaite et al., colour and felt emotion review (Benjamins)](https://www.jbe-platform.com/content/books/9789027244185-z.244.03jon); [paintdb: comparing paint colours (LRV)](https://paintdb.com/blog/how-to-compare-paint-colors-side-by-side); [US EPA: VOCs and indoor air](https://www.epa.gov/indoor-air-quality-iaq/volatile-organic-compounds-impact-indoor-air-quality); [PNNL BASC: low-emission paints](https://basc.pnnl.gov/resource-guides/certified-lowno-emission-interior-paints-and-finishes).

## 7. Rugs, art and windows (trade conventions)

No standard covers these; the figures are what the trade usually does, mostly in Western-style rooms.

- **Rugs.** Many rooms do well without one: tiled rooms in hot climates, rooms used by someone with a walker (§10). Where there is one, common conventions run from largest to smallest: all of a seating group's furniture on the rug; only the front legs of the seating; a small rug no furniture touches. A rug that floats with a leg or two just touching often reads as undersized. Dining rugs usually run about 60 cm (24 in) past the table on every side so chairs stay on when pulled out. Around a room-size rug, sources leave about 15–45 cm (6–18 in) of floor showing. Pile, flat-weave (kilim, dhurrie), natural fibre (jute, sisal) and layered rugs all have their place; floor-seating traditions use rugs and mats differently. Use a non-slip pad.
- **Art.** Galleries commonly hang the centre of a piece about 145–152 cm (57–60 in) above the floor; above furniture, the bottom of the frame about 15–25 cm (6–10 in) above it. Hang lower where people mostly sit on chairs or the floor, and for children. A gallery wall or salon hang (many frames close together) is a fine choice: treat the group as one piece, start from an anchor piece and keep the gaps consistent.
- **Window treatments.** Mounting the rod above the frame (from about 10–15 cm, 4–6 in, up to most of the way to the ceiling) and past its sides lets open curtains clear the glass, so the window reads larger and keeps its daylight. Floor-length panels are common; over a radiator, heater or vent, use sill-length curtains, blinds or shutters so the heat isn't trapped. In hot climates, shutters, external blinds and lined curtains are about heat as much as looks (§8).

Sources (industry convention): [Ruggable size guide](https://ruggable.com/pages/size-guide); [Revival rug size guide](https://lp.revivalrugs.com/pages/shop-area-rug-size-guide); [Framebridge: hanging height](https://www.framebridge.com/blogs/how-to-s/what-is-the-right-height-to-hang-a-frame); [Eden Gallery: how high to hang art](https://eden-gallery.com/news/how-high-should-you-hang-art-on-a-wall); [TaskRabbit: how high to hang curtains](https://www.taskrabbit.com/blog/how-high-to-hang-curtains).

## 8. Heat, cold, air and sound

- **Keeping cool.** Stop the sun before it reaches the glass (external shutters, awnings, blinds; inside, light-coloured lined curtains drawn by day); WHO heat-health guidance also advises cooling the home with night air and cutting heat from appliances by day. Arrange furniture so air can cross the room between windows. Keep the airflow of fans and wall-mounted air conditioners clear: no tall pieces right under or in front of an AC unit, and its stream not aimed at beds or seats.
- **Ceiling fans.** Blades at least 2.1 m (7 ft) above the floor and about 75 cm (30 in) from walls and obstructions (manufacturers' installation guidance and safety listings such as UL, CE or BIS; check the fan's manual). Size the fan to the room with the maker's chart, and keep tall furniture and pendant lights out of its sweep.
- **Keeping warm.** The WHO proposes at least 18 °C (64 °F) indoors in cold seasons in temperate and colder climates (a policy benchmark; the evidence for the exact threshold is limited). Keep furniture and long curtains off radiators, heaters and vents. Close-fitting cellular (honeycomb) shades cut heat loss through windows the most of common coverings: US Department of Energy simulations found up to 20% heating-energy savings against no shades.
- **Damp and mould.** Persistent dampness and mould raise the risk of respiratory symptoms and asthma (WHO). Keep air moving in humid rooms and behind furniture on cold outside walls, and choose finishes and fabrics that cope with humidity.
- **Echo and noise.** Hard, parallel surfaces echo; rugs, upholstery, curtains, bookshelves and soft wall pieces absorb or scatter sound. Soft furnishings tame echo but do little against traffic or neighbours, which takes mass and airtight seals. For sleep, WHO guidance aims at about 30 dB(A) average in bedrooms at night; put beds on the quiet side where there is a choice.

Sources: [WHO/Europe: #KeepCool in the heat](https://www.who.int/europe/news-room/fact-sheets/item/keepcool-in-the-heat); [Hunter Fan: blade clearances under UL and ETL](https://support.hunterfan.com/hc/en-us/articles/360042826873); [WHO Housing and Health Guidelines (2018), indoor cold](https://www.ncbi.nlm.nih.gov/books/NBK535294/); [US DOE: cellular shades fact sheet (PDF)](https://www.energy.gov/sites/default/files/2021-12/bto-cellular-shades-factsheet-112221.pdf); [WHO guidelines for indoor air quality: dampness and mould](https://www.who.int/publications/i/item/9789289041683); [WHO Guidelines for Community Noise (1999)](https://www.who.int/publications/i/item/a68672).

## 9. Storage and display

- Store things where they're used, at a height that suits how often they're used: daily items between knee and shoulder height (the reach range in §4; lower for wheelchair users and children).
- Balance closed storage, for what the person doesn't want to see, with open display for what they do. Collectors may want mostly display: vitrines, open shelves, a rotating selection.
- Plan a landing place for what arrives every day: keys, bags, shoes, mail, school gear, a pet's things.

## 10. Accessibility and ageing in place

Design so the room works for everyone who uses it, now and later. Most of it costs little when planned in. Ask about specific needs rather than assuming; an occupational therapist's assessment beats any general figure.
- **Getting around:** main routes 900 mm (36 in) or wider; doorways 800–815 mm (32 in) clear or wider; a 1500 mm (60 in) turning circle where a wheelchair user turns (§3); as few changes in floor level and thresholds as possible.
- **Using things:** a clear floor space in front of what people use (a sink, a wardrobe, a bed side): 760 × 1220 mm (30 × 48 in) in US guidance, 750–1000 mm wide in UK guidance. Knee space under tables, desks and sinks a wheelchair user works at: about 685 mm (27 in) high and 760 mm (30 in) wide (ADA 306). Reach and switch heights as in §4; lever handles and rocker switches over knobs; a mirror usable seated.
- **Beds and seats:** a clear transfer side at the bed and favourite seat; a bed surface near the wheelchair's seat height (sources suggest within a few cm, with a firm mattress), checked with the person; firm seats with arms, at a height that's easy to rise from.
- **Walkers and canes:** no loose rugs on walking routes, or only low, fully gripped ones with bevelled edges; something stable to hold along routes.
- **Low vision:** bright, even light without dark gaps between rooms (§5); contrast at steps, edges and door frames (§6); night lights on the route to the bathroom.

Sources: [2010 ADA Standards, ch. 3 (incl. 306 knee and toe clearance)](https://www.access-board.gov/ada/chapter/ch03/); [UK Approved Document M, vol. 1](https://assets.publishing.service.gov.uk/media/5a7f8a82ed915d74e622b17b/BR_PDF_AD_M1_2015_with_2016_amendments_V3.pdf); [AARP HomeFit Guide](https://www.aarp.org/livable-communities/housing/info-2020/homefit-guide.html); [LRC / AARP lighting principles (archived)](https://web.archive.org/web/2022/https://www.lrc.rpi.edu/programs/lightHealth/AARP/designers/lightingOlderAdults/lightingPrinciples.asp); [India: Harmonised Guidelines for Universal Accessibility (2016 ed., PDF)](https://sje.gujarat.gov.in/dsd/assets/downloads/harmonised_guidelines_23032016.pdf); [South Africa: SANS 10400-S (regulation text)](https://source.acts.co.za/national-building-regulations-and-building-standards-act-1977/r2378_s3__deemed-to-satisfy_re.php); [Brazil: ABNT NBR 9050 (summary, Portuguese)](https://sienge.com.br/blog/nbr-9050-acessibilidade/); [China: GB 55019-2021 (catalogue entry)](https://www.chinesestandard.net/Related.aspx/GB55019-2021).

## 11. Safety

- **Tip-overs.** Anchor dressers, bookcases, cabinets and TVs to the wall, above all where children are: in the US most child tip-over deaths involve a falling TV, and most victims are under five. New clothing storage must meet ASTM F2057-23 in the US and is tested to EN 14749 in Europe; Australia requires tip-over warnings at sale. Older furniture meets none of this, so anchor it too.
- **Earthquake zones and homes where drilling isn't allowed.** Fix tall furniture with L-brackets and screws where the wall allows; where it doesn't, use ceiling tension poles with base stoppers, straps or anti-slip mats (fire-service guidance in Japan). Keep tall or heavy pieces from falling onto beds, seats or exits, and keep heavy things low.
- **Children.** Hardware-mounted gates at the top of stairs (pressure gates only at the bottom); glass tables, sharp corners and hot surfaces at toddler height; socket covers where sockets have no built-in shutters; a pool or pond fenced on all sides with a self-closing, self-latching gate (CPSC: at least 1.2 m, 4 ft).
- **Window coverings.** Choose cordless or inaccessible-cord blinds where children live or visit; the US, EU (EN 13120) and Australia all regulate cord loops.
- **Windows and climbing.** Keep beds, sofas and anything climbable away from windows in children's rooms; limit openings to under 10 cm (4 in) with stops or restrictors an adult can release quickly in an emergency. Screens don't stop falls.
- **Bunk beds.** Children under six shouldn't sleep on the top bunk; guardrails on both sides.
- **Cords and power.** Don't run cords under rugs or furniture. Extension cords are temporary: add sockets (outlets) where a layout needs them, or ask the landlord; until then a short, rated cord. Never plug a space heater into an extension cord or power strip.
- **Heat and flame.** Keep anything that burns at least 0.9 m (3 ft) from heaters, fireplaces and stoves. Candles: at least 30 cm (12 in) from anything that burns, 10 cm (4 in) apart, never under shelves. Oil lamps (diyas), incense and burners: on a stable, heat-proof surface, well clear of curtains, decorations and clothing. Never leave any flame unattended; LED candles are the safe stand-in.
- **Backup power.** Never run a generator indoors, in a garage or near openings: keep it at least 6 m (20 ft) from windows, doors and vents (CDC), and fit a carbon monoxide alarm. Keep inverter and battery systems ventilated, clear of anything flammable and easy to reach, as their installer specifies.
- **Pets.** Check every plant against a toxic-plant list for the household's animals (lilies are deadly to cats; sago palms to dogs), and keep cords and small objects out of reach of chewers.

Sources: [CPSC: tip-over report (2023)](https://www.cpsc.gov/Newsroom/News-Releases/2023/Plans-to-Watch-the-Big-Game-on-the-Big-Screen-CPSC-Reminds-Families-to-Protect-Children-from-the-Deadly-Hazard-of-Toppling-TVs-and-Furniture); [Federal Register: clothing storage units, ASTM F2057-23](https://www.govinfo.gov/content/pkg/FR-2023-05-04/html/2023-08997.htm); [BSI: EN 14749](https://knowledge.bsigroup.com/products/furniture-domestic-and-kitchen-storage-units-and-kitchen-worktops-safety-requirements-and-test-methods); [ACCC: toppling furniture](https://www.accc.gov.au/media-release/new-laws-to-increase-awareness-of-the-dangers-of-toppling-furniture); [Tokyo Fire Department: securing furniture](https://www.tfd.metro.tokyo.lg.jp/eng/merumaga/info_en_2017nov.html); [Shinjuku City: preventing furniture from falling](https://www.city.shinjuku.lg.jp/anzen/kikikanri01_english07.html); [Consumer Reports: hardware vs. pressure-mounted gates](https://www.consumerreports.org/cro/news/2009/01/hardware-mounted-vs-pressure-mounted-child-safety-gates/index.htm); [CPSC: pool fencing](https://www.cpsc.gov/Newsroom/News-Releases/1989/Pool-Fencing-Can-Prevent-Child-Drownings); [CPSC: corded window coverings](https://www.cpsc.gov/Regulations-Laws--Standards/Rulemaking/Final-and-Proposed-Rules/Corded-Window-Coverings); [CCPC Ireland: window blinds (EN 13120)](https://www.ccpc.ie/consumers/product-safety/child-safety/window-blinds/); [Harborview Injury Prevention: four inches](https://hiprc.org/blog/four-inches-are-key-to-preventing-window-falls/); [Nationwide Children's: bunk beds](https://www.nationwidechildrens.org/research/areas-of-research/center-for-injury-research-and-policy/injury-topics/home-safety/bunk-bed-safety); [ESFI: extension cords](https://esfi.org/extension-cord-safety); [US Fire Administration: heating](https://www.usfa.fema.gov/prevention/home-fires/prevent-fires/heating/); [Dorset & Wiltshire Fire: Diwali lamp safety](https://www.dwfire.org.uk/safety/safety-at-home/seasonal-advice/diwali); [London Fire Brigade: shrine oil-lamp fire](https://www.london-fire.gov.uk/incidents/2024/july/house-fire-harrow); [CDC: carbon monoxide from generators](https://www.cdc.gov/nceh/multimedia/infographics/carbon_monoxide_danger.html); [EPRI: residential battery storage safety](https://restservice.epri.com/publicdownload/000000003002026399/0/Product); [ASPCA: toxic and non-toxic plants](https://www.aspca.org/pet-care/animal-poison-control/toxic-and-non-toxic-plants).

## 12. Sustainability

- The greenest piece is the one already owned. Rearrange, refinish, re-cover or move things between rooms before buying.
- Secondhand and vintage pieces, and pieces made by a local maker, can cost less and last longer than new; judge each on its construction.
- Buy durable and repairable over disposable: solid frames, replaceable covers and cushions, standard bulbs and parts.
- Use efficient lighting (LED), low-emission finishes, and window coverings that keep heat in or out (§8).
- Measure before ordering: returns of bulky pieces waste money, time and freight.

## 13. Buying and making

- **Spec sheet first.** Get width, depth, height, seat and arm heights, and diagonal depth from the maker. Model the piece at those sizes and check it against soffits, door swings, keep-clear zones and the neighbouring pieces.
- **Made to order.** For a local carpenter, upholsterer or metalworker, hand over a dimensioned drawing (plan, front and side, from the model), materials, finish and hardware, and the tolerances that matter (fit between walls, under a window).
- **The delivery path.** Measure every door, hall, stair, lift and turn on the way in at its narrowest point, and compare with the piece's diagonal depth. Check whether its legs come off or it ships in sections.
- **Fit the room the person wants.** Size each piece against its neighbours as well as the wall, at the fullness the person likes (§1): some want space around each piece, others a richly filled room.
- **Trust, but verify.** Read recent negative reviews and look at customer photos, which show colour and scale better than studio shots. Check the return policy and delivery cost, in the person's own market and currency. Look at price history before calling something a deal, and never invent urgency.
- **Offer choices.** Give a recommendation with reasons, and alternatives at other price points or sourcing (new, secondhand, antique, made to order), as the household prefers.

Sources (retailer guidance): [Frontgate: measure for delivery](https://www.frontgate.com/homeplusstyle/?p=12439); [The English Sofa Company: access guide](https://www.theenglishsofacompany.co.uk/furniture-access-guide); [Design Within Reach: delivery guide](https://www.dwr.com/furniture-delivery-guide.html?lang=en_CA).

## 14. Leave room for creativity

- Rooms people love usually have something only they would choose: a collection, a colour, a piece with a story. Ask about it and design around it.
- Treat style names as conversation starters, not specs. Mixing eras, cultures and styles is normal.
- When a principle and the person's taste disagree, show both, explain the trade-off once, and then go with their choice. Safety risks (to children, older people, fire, tip-overs) are the exception: list them in the report's safety section, not only in conversation.
- Change one thing at a time when testing options, so the person can see what each choice does.
