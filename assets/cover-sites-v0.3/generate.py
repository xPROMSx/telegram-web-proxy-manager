#!/usr/bin/env python3
"""Original static cover-site candidates for TWPM. stdlib only; no network access.

Generates one stable site per invocation, with unique icons and article notes. This is a design prototype and NOT an
installer, Telemt patch, migration, or anti-probing guarantee.
"""
import argparse
import html
import json
import re
import secrets
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent

DATA = {
    'botanical': {
        'brands': ['Fern & Window', 'The Leaf Register', 'Quiet Canopy', 'Green Margin',
                   'North Window', 'Little Conservatory', 'Moss & Morning', 'The Plant Almanac',
                   'Glasshouse Pages', 'Soft Fern', 'Veranda Notes', 'Root & Light',
                   'Common Leaf', 'Houseplant Journal', 'Seasoned Green', 'A Window Garden'],
        'colors': [('#183b32','#f3f2ea','#e0e8d7','#8b563e'),('#27443e','#f8f4ed','#d7e6dc','#895440'),
                   ('#31452b','#f5f1e8','#e7e8d0','#835c32'),('#1c4645','#f1f5f0','#d8e6e4','#865542'),
                   ('#33462e','#f8f5ed','#eceddc','#925842'),('#294b40','#f2eee6','#dce7d6','#8b5449')],
        'copy': [
            ('Small rituals, greener rooms.', 'A practical field journal for looking after the plants that make a room feel lived in.', 'NOTICE WHAT CHANGES'),
            ('Grow with the light you have.', 'Clear, measured advice on everyday plant care, windowsill experiments and seasonal habits.', 'THE EVERYDAY GARDEN'),
            ('A considered place for leaves.', 'Simple observations and reliable routines for indoor plants, without miracle fixes.', 'ROOM TO GROW'),
            ('Notes from the windowsill.', 'A collection of useful plant-care notes, written for the ordinary conditions of an ordinary home.', 'A QUIETER KIND OF GREEN'),
            ('Good growing starts with noticing.', 'Light, water, soil and the small adjustments that help houseplants settle in.', 'THE GREEN NOTEBOOK')],
        'pages': [('index.html','Home'),('light.html','Light'),('watering.html','Watering'),('plants.html','Plants'),('field-notes.html','Field notes')],
    },
    'night-sky': {
        'brands': ['Evening Meridian','Night Atlas','The Quiet Orbit','After Dusk','Open Sky Almanac','North Star Notes',
                   'Blue Hour Fieldbook','Orbit & Horizon','Nightfall Observer','Starlit Pages','Celestial Notebook',
                   'The Wide Night','Dark Sky Reader','Skyward Journal','Moonline','The Observatory Notes'],
        'colors': [('#cda970','#0a1523','#142639','#a8c1d5'),('#a6b9e4','#0c1528','#182844','#9ed3d4'),
                   ('#e0b78c','#111622','#252c3c','#b2c6d5'),('#9dc9c9','#091b25','#17323a','#a8c6cd'),
                   ('#c9b5f0','#111326','#292441','#b8b6e3'),('#e8bd82','#101922','#2b3338','#bbd0db')],
        'copy': [
            ('Look up. Stay curious.', 'A calm and practical guide to the night sky, from first constellations to the changing Moon.', 'FIELD NOTES FROM AFTER DARK'),
            ('A wider world above us.', 'Learn your way around the night sky with patient observations and simple equipment.', 'AN OBSERVER’S COMPANION'),
            ('The sky rewards a second look.', 'Seasonal guides and careful notes for anyone curious about what appears after sunset.', 'UNDER THE SAME SKY'),
            ('Find your bearings after dusk.', 'An independent field guide to stars, lunar phases and the art of looking carefully.', 'THE NIGHTLY FIELD GUIDE'),
            ('Night has a map of its own.', 'Accessible astronomy notes for unhurried evenings beneath a clear sky.', 'NOTES ON THE HEAVENS')],
        'pages': [('index.html','Overview'),('tonight.html','Getting started'),('moon.html','The Moon'),('constellations.html','Star patterns'),('equipment.html','Equipment')],
    },
    'kitchen': {
        'brands': ['The Everyday Table','Apron Notes','Salt & Season','The Quiet Kitchen','Pantry Letter','Daily Simmer',
                   'Supper & Stone','A Small Plate','The Home Cook Journal','The Open Pantry','Honest Ingredients',
                   'Good Things Cooking','The Kitchen Leaf','Table & Thyme','A Simple Supper','Common Recipe'],
        'colors': [('#8d3b29','#fff9f0','#f2e7d7','#426e56'),('#974c32','#fff8ec','#f6e3d0','#4e6b55'),
                   ('#773c34','#fcf7ee','#f0e5db','#4b6b5a'),('#91582d','#fff8ed','#e9e8d5','#566a48'),
                   ('#a14a43','#fff9f5','#f3e3df','#516a58'),('#844b3b','#fdf8f0','#f0e8d5','#4f6b59')],
        'copy': [
            ('A little more care, every meal.', 'Honest, approachable cooking notes for ordinary ingredients and busy evenings.', 'HOME COOKING, NOT COMPLICATED'),
            ('Make something good from simple things.', 'A warm collection of reliable techniques, seasonal ideas and everyday recipes.', 'NOTES FROM THE TABLE'),
            ('A kitchen worth coming home to.', 'Unhurried recipes, sensible pantry ideas and the small skills that make cooking easier.', 'GOOD FOOD, NO FUSS'),
            ('Good meals begin with basics.', 'Clear recipes and useful kitchen habits, gathered for the curious home cook.', 'A PRACTICAL FOOD JOURNAL'),
            ('Everyday ingredients. Better dinners.', 'Cook with what you have, learn one useful technique and enjoy the result.', 'THE HOME TABLE')],
        'pages': [('index.html','Home'),('recipes.html','Recipes'),('pantry.html','Pantry'),('techniques.html','Techniques'),('seasons.html','Seasons')],
    },
}

ARTICLE = {
 'botanical': {
  'light.html':('Light is a location, not a label','HOW TO READ A ROOM',[
      ('Start with the window','Light is strongest close to the glass and usually falls quickly across the room. Begin by noticing where direct sun lands in the morning and afternoon.'),
      ('Watch the leaves','Plants that receive too little light often stretch toward a window, while sudden harsh sunshine can damage leaves adapted to shade. Change positions gradually.'),
      ('Use a simple record','Write down the window direction and approximate hours of direct sun. Check new growth after a few weeks before making another adjustment.')], 'One small experiment: move a plant a little closer to the window and record how its newest leaves develop.'),
  'watering.html':('Water according to the pot, not the calendar','A BETTER WATERING ROUTINE',[
      ('Feel below the surface','Touch the potting mix a little below the top layer. A dry surface alone does not tell you whether the root zone needs water.'),
      ('Water thoroughly, then drain','If the plant needs watering, moisten the mix evenly and allow excess to leave the pot. Empty standing water from outer containers.'),
      ('Check the conditions','A plant in bright light and warm air may use water faster than the same species in a cooler, dimmer room. Pot size and soil texture matter too.')], 'A weekly check is useful; a mandatory weekly watering is not.'),
  'plants.html':('Five plant habits worth learning','INDOOR PLANT FIELD GUIDE',[
      ('Pothos','A flexible trailing plant that tolerates a range of indoor conditions. Give it indirect light and watch soil moisture rather than following a strict schedule.'),
      ('Spider plant','Often grows well with bright indirect light. Browning tips can have several causes; avoid changing everything at once.'),
      ('ZZ plant','Stores moisture in its rhizomes and generally prefers the mix to dry between waterings.'),
      ('Peace lily','Its leaves often droop when thirsty, though repeated wilting is stressful. Give it filtered light and good drainage.'),
      ('Snake plant','Adaptable and slow growing. A free-draining mix and restraint with watering are more helpful than frequent fussing.')], 'Plant names are useful starting points. Your particular light, pot and room still determine the routine.'),
  'field-notes.html':('A small journal makes care easier','OBSERVATION OVER ASSUMPTION',[
      ('What to record','Note the date, plant, location, soil feel, and anything that changed. Two lines are usually enough.'),
      ('What not to change at once','If a leaf yellows, avoid simultaneously moving the plant, repotting it and adding fertilizer. Small, separate changes are easier to understand.'),
      ('The monthly review','Compare new growth and general leaf condition with your earlier notes. Healthy change is usually gradual.')], 'Try this: choose one plant and keep a four-week log. The useful result is a pattern, not a perfect score.'),
 },
 'night-sky': {
  'tonight.html':('Your first evening under the stars','START SMALL',[
      ('Find a dark, safe place','A clear view away from direct street lights helps. You do not need an isolated site; a familiar local park can be enough.'),
      ('Let your eyes adjust','Give your eyes time away from bright screens and lamps. Even ten to twenty minutes can make faint stars easier to notice.'),
      ('Start with one landmark','Find a familiar bright star or recognizable pattern. Learning a single direction and returning the next evening builds confidence.')], 'A red-light setting and a paper note can help preserve your night vision.'),
  'moon.html':('The Moon changes its shape, not its size','LUNAR OBSERVATION',[
      ('Why phases happen','Half of the Moon is illuminated by the Sun. From Earth, we see different portions of that illuminated half as the Moon orbits us.'),
      ('Try the terminator','The boundary between lunar day and night casts long shadows. Binoculars can reveal craters particularly well near that line.'),
      ('Observe again tomorrow','Sketch the visible phase at roughly the same local time on consecutive nights. Notice how the illuminated area changes.')], 'The phase is not Earth’s shadow except during a lunar eclipse.'),
  'constellations.html':('Patterns that help you navigate','A SKY OF REFERENCE POINTS',[
      ('Use the horizon','Begin by checking which direction you face. Star patterns change with season, latitude and time of night.'),
      ('Think in shapes','Look for simple arrangements of bright stars before trying to memorize dozens of names.'),
      ('Return in another month','The same constellation appears at different times as Earth travels around the Sun. Your observations become a seasonal clock.')], 'A printed star chart should be matched to your location, date and time.'),
  'equipment.html':('Begin without a telescope','CHOOSING SIMPLE TOOLS',[
      ('Unaided eyes first','Learn the principal bright stars and the Moon. Observing without equipment also teaches patience and orientation.'),
      ('Binoculars can be enough','A steady, manageable pair can show lunar details and bright star clusters. A simple support may help.'),
      ('Avoid chasing magnification','Stability, clear optics and a dark observing location usually matter more than an impressive magnification number.')], 'Weather, clouds and local light pollution often limit what can be seen more than equipment does.'),
 },
 'kitchen': {
  'recipes.html':('Three weeknight ideas with room to improvise','A SMALL RECIPE NOTEBOOK',[
      ('Lemony beans on toast','Warm canned beans gently with olive oil, garlic and a little water. Finish with lemon zest and parsley. Spoon over toasted bread.'),
      ('Roasted vegetables with yogurt','Cut vegetables to similar sizes, coat lightly with oil and roast until browned and tender. Serve with plain yogurt, herbs and salt.'),
      ('Tomato and rice soup','Soften onion in a little oil, add tomato and stock, then simmer rice until tender. Add extra liquid as needed and finish with black pepper.')], 'Recipes are starting points: taste before serving and adjust salt, acidity and texture.'),
  'pantry.html':('A small pantry can do more','INGREDIENTS THAT EARN THEIR PLACE',[
      ('Choose flexible staples','Rice, pasta, lentils, canned tomatoes and beans can become many different meals with a few fresh ingredients.'),
      ('Add flavor deliberately','Oil, vinegar, spices, mustard and citrus can change a dish more efficiently than a crowded cupboard.'),
      ('Store with intention','Keep dry foods sealed and dated. Make frequently used ingredients visible so they do not disappear behind new purchases.')], 'Build a pantry around dishes you genuinely cook, not an idealized list.'),
  'techniques.html':('Good cooking comes from small decisions','KITCHEN FOUNDATIONS',[
      ('Heat the pan, then pay attention','The same food can steam or brown depending on moisture, temperature and how crowded the pan is.'),
      ('Season in stages','Add modest amounts of salt as you cook and taste near the end. Acidity can bring a flat dish into focus.'),
      ('Rest before cutting','Some roasted or seared foods benefit from a brief rest. This can make serving easier and the final texture more even.')], 'Learning one technique is often more useful than collecting ten new recipes.'),
  'seasons.html':('Cook with the season you have','A RHYTHM FOR THE TABLE',[
      ('Spring','Look for fresh greens and tender herbs. Keep preparations light and avoid hiding delicate flavors under heavy sauces.'),
      ('Summer','Tomatoes, berries and crisp vegetables work well with simple dressings and minimal cooking.'),
      ('Autumn and winter','Roasted roots, grains, beans and warming soups are practical ways to use sturdy ingredients.')], 'Seasonal availability differs by region; local markets are a better guide than a universal calendar.'),
 },
}


# Additional independently written observations. One is selected for each article
# at build time; all are evergreen and require no simulated authors or updates.
EXTRA_NOTES = {
 'botanical': {
  'light.html': [
   ('Try a paper shadow test','Hold a sheet of paper beside the plant at midday. A distinct shadow suggests direct light; a soft one suggests diffused light. Repeat on another day before drawing conclusions.'),
   ('Notice seasonal movement','The same window receives light at different angles through the year. A place that feels gentle in winter may become intense in summer.'),
   ('Rotate only when needed','A quarter turn every so often can help even out growth, but plants with fragile stems or flowers may prefer to stay in one position.'),
   ('Separate light from heat','A bright pane can also be hot or cold. Keep foliage away from extreme glass temperatures even when the light itself seems suitable.')],
  'watering.html': [
   ('Lift the pot','Learning the difference between the weight of a wet and dry pot gives you another practical signal, especially for small containers.'),
   ('Watch the saucer','A little runoff shows water reached the bottom. Pour away standing water so roots do not remain submerged.'),
   ('Change the routine slowly','After moving a plant to a brighter room, check moisture more often before automatically increasing the amount of water.'),
   ('Check the drainage holes','A pot without an escape route needs a different approach. For many common houseplants a drainage hole makes consistent watering much easier.')],
  'plants.html': [
   ('Look at new growth','A new leaf or shoot is often a more useful indicator of present conditions than an old leaf damaged months ago.'),
   ('Read the label carefully','Common plant names vary by region. A botanical name can help when comparing care guidance for similar-looking species.'),
   ('Introduce plants gradually','A newly bought plant needs time to adapt. Keep it apart from the collection briefly while checking for pests and environmental stress.'),
   ('Make room for growth','Check mature size before choosing a location. The right shelf today may be cramped after another growing season.')],
  'field-notes.html': [
   ('Photographs help','Take a quick picture from the same angle each month. Side-by-side images can reveal gradual growth that is easy to miss daily.'),
   ('Record one cause at a time','When you change light, water or position, write down the date and wait before adding another variable.'),
   ('Keep the record small','A two-column note for date and observation is usually enough. The system should be easier than remembering every detail.'),
   ('Include the weather','A long stretch of hot or cloudy days may explain changes that otherwise look mysterious. Add this context to the journal.')]
 },
 'night-sky': {
  'tonight.html': [
   ('Keep directions simple','Use a compass to mark north, then compare the same skyline with a star map. Avoid relying on memory alone when learning new patterns.'),
   ('Plan for the weather','Thin cloud and bright Moonlight can obscure faint objects. A disappointing evening may be about conditions, not your technique.'),
   ('Bring a warm layer','Standing still outdoors becomes chilly surprisingly quickly. Comfort helps you concentrate on observation rather than the clock.'),
   ('Begin with a short visit','Fifteen minutes with one clear goal often teaches more than a long session spent searching for everything at once.')],
  'moon.html': [
   ('Compare the shadows','Near the terminator, changing sunlight makes crater rims and mountains stand out. Observe the same feature over several evenings.'),
   ('Look for Earthshine','A thin crescent sometimes appears to hold a faintly visible dark disk. That gentle glow comes from sunlight reflected by Earth.'),
   ('Notice the rising time','The Moon does not rise at the same hour each day. Check local predictions before planning an evening observation.'),
   ('Use stable support','Resting binoculars against a railing or using a tripod can reveal more detail than simply increasing magnification.')],
  'constellations.html': [
   ('Use a familiar anchor','Once you recognize one bright star or distinctive pattern, trace neighboring stars outward rather than attempting the whole sky.'),
   ('Respect your latitude','Some constellations remain hidden below the horizon from certain regions. A chart tailored to your latitude avoids impossible targets.'),
   ('Check the season','The night side of Earth faces different directions over the year. A spring chart will not match a winter evening.'),
   ('Sketch the relationships','Draw only the brightest stars first and add fainter ones later. Simple relative distances matter more than artistic accuracy.')],
  'equipment.html': [
   ('Choose a comfortable grip','A lightweight pair of binoculars you can hold steadily may be more useful than larger optics that quickly tire your arms.'),
   ('Give optics time','Moving a telescope from a warm room to cold air can affect the view. Allow temperature to settle before evaluating sharpness.'),
   ('Protect your eyes','Never view the Sun directly through binoculars or a telescope without a purpose-built, properly fitted solar filter.'),
   ('Carry less at first','A chair, a printed chart and one pair of binoculars are enough for many rewarding nights. Master the basics before adding accessories.')]
 },
 'kitchen': {
  'recipes.html': [
   ('Finish with contrast','A little lemon, vinegar or a fresh herb can brighten a rich dish. Add it near the end and taste again.'),
   ('Keep portions flexible','Plan around how many people are eating and what is already in the fridge. Simple recipes tolerate sensible substitutions.'),
   ('Use leftovers with intent','Cook extra grains or beans once, cool them promptly, and turn them into a different meal the following day.'),
   ('Work in a sensible order','Before heating a pan, wash and cut the ingredients that need attention. A calm start prevents rushed seasoning.')],
  'pantry.html': [
   ('Label opened packages','The date you open a flour bag or jar can be more useful than relying on memory when reorganizing a cupboard.'),
   ('Store spices away from heat','A shelf over the hob is convenient but often too warm. A cool, dry cupboard helps aromas last longer.'),
   ('Keep one emergency meal','A few ingredients for a familiar soup, pasta or bean dish make busy evenings easier without extra shopping.'),
   ('Use the oldest first','Move new packages behind existing ones when you restock. Small habits reduce forgotten food and unnecessary waste.')],
  'techniques.html': [
   ('Dry the surface','Patting vegetables or proteins dry before searing can help them brown rather than steam in the pan.'),
   ('Control the crowd','Cook in batches if the pan cools sharply after adding ingredients. Too much food at once slows browning.'),
   ('Use gentle heat','Eggs, dairy-based sauces and delicate fish often need less heat than you expect. Lower the temperature before they toughen.'),
   ('Taste at the table','The final adjustment may be salt, acidity or texture. Make small changes and taste rather than adding everything together.')],
  'seasons.html': [
   ('Shop by quality','Seasonal calendars are useful hints, but actual produce quality and local weather should guide your choice.'),
   ('Keep the preparation light','When fresh ingredients are flavorful, oil, salt and a quick cooking method are often enough.'),
   ('Save for later','Freeze or preserve surplus ingredients using established food-safety guidance rather than leaving them to spoil.'),
   ('Make a weekly note','Write down one seasonal ingredient you enjoyed and how you prepared it. Over time you will build a useful personal menu.')]
 }
}


# Independent, fully written alternate article structures. They are selected once
# when publishing a new site; none relies on invented dates, authors, or feeds.
ARTICLE_ALTERNATES = {
 'botanical': {
  'light.html': [
   ('Reading the light on a windowsill', 'WINDOW OBSERVATIONS', [
    ('Begin with the room', 'Stand where the plant will live and watch the room on two ordinary days. Note when the glass admits direct sun, and where nearby walls or trees cast shade.'),
    ('Consider distance', 'A bright-looking room is not equally bright everywhere. A shelf two metres from the window can receive much less usable light than a sill just beside it.'),
    ('Make one adjustment', 'Move a struggling plant a modest distance rather than changing its soil, water and location together. Compare the next few leaves with the older growth.')],
    'A north-facing window and a shaded south-facing window can feel similar. Observing the actual light matters more than a compass label.'),
   ('When a room is bright but the plant is not', 'LIGHT IN PRACTICE', [
    ('Watch the clock', 'Early sun may be gentle while a late afternoon beam is intense. Check which hours the plant really receives sun instead of estimating from the room as a whole.'),
    ('Read slow changes', 'A stretched stem or longer gaps between leaves can indicate insufficient light. One pale leaf, on its own, is rarely enough evidence to diagnose the cause.'),
    ('Mind the seasons', 'The angle of sunlight shifts during the year. Recheck familiar places when the seasons change, especially where leaves may touch hot or cold window glass.')],
    'If you cannot explain a change, take a photograph and wait for new growth before moving the plant again.')],
  'watering.html': [
   ('Understanding moisture beneath the surface', 'NOTES ON WATER', [
    ('The surface can mislead', 'The top of a pot may feel dry while the lower root zone remains wet. Test a little deeper and compare the pot weight before reaching for the watering can.'),
    ('Give water somewhere to go', 'A container with drainage makes it easier to water evenly and discard the excess. Water should not sit indefinitely inside a decorative outer pot.'),
    ('Observe the next days', 'Check how quickly the soil changes after a thorough watering. The useful interval is the one your plant and environment produce, not a fixed number on a calendar.')],
    'Watering less often is not the same as using only a tiny amount of water. When watering is needed, even coverage and drainage matter.'),
   ('A kinder routine for potted plants', 'POTS AND PATIENCE', [
    ('Know the mix', 'Dense compost holds water differently from a chunky, airy blend. Two identical plants in different mixes may require quite different checks.'),
    ('Look at the pot', 'Small terracotta pots often dry differently from large glazed containers. Size, material and drainage all influence how long moisture remains.'),
    ('Notice the room', 'Warm moving air, strong light and vigorous new growth can increase water demand. A cool, dim period usually calls for more caution before watering again.')],
    'When the pot feels unusually heavy for many days, look at drainage and the mix rather than automatically increasing watering.')],
  'plants.html': [
   ('Choose the right plant for the place', 'A ROOM-BY-ROOM GUIDE', [
    ('For a bright shelf', 'Many peperomias appreciate a position with generous indirect light. Their leaf textures differ, so check the particular variety before assuming identical care.'),
    ('For a trailing corner', 'A healthy hoya can make a patient, long-lived indoor vine. Give it a stable position and avoid repeatedly changing conditions to chase rapid growth.'),
    ('For an open floor', 'A rubber plant needs space as it matures. Check ceiling height and the direction of light before choosing a long-term place for a young specimen.')],
    'Start by matching a plant to the conditions you have; buying a demanding species first can turn ordinary care into a constant rescue effort.'),
   ('Plant care begins before watering', 'LOOK AT THE ROOTS OF THE PROBLEM', [
    ('Start with a healthy plant', 'Check both sides of leaves, stems and the soil surface before bringing a new plant home. Small changes are easier to notice when you know its starting condition.'),
    ('Give it time to settle', 'Many plants react to changes in temperature, light and humidity. Observe for a while before repotting or adjusting every part of the routine.'),
    ('Plan for mature size', 'A compact nursery plant may eventually need a larger shelf or floor space. Read about its growth habit before deciding where to keep it.')],
    'An attractive leaf is a beginning, not a care plan. The right place and suitable container usually matter more than a complicated schedule.')],
  'field-notes.html': [
   ('A notebook for the changing seasons indoors', 'A SIMPLE RECORD', [
    ('Capture the starting point', 'Write down the plant name, pot size and window position. One clear photo helps when you return to the note later.'),
    ('Keep observations separate', 'Record what happened before writing a possible cause. A yellowing leaf is an observation; lack of water is only one possible explanation.'),
    ('Compare monthly', 'Look for the direction of new growth and the condition of the newest leaves. Slow improvement can be more meaningful than a dramatic change in one afternoon.')],
    'A short record you actually keep is better than a detailed chart abandoned after three days.'),
   ('Learn from one plant at a time', 'HOME GROWING LOG', [
    ('Pick a small question', 'Instead of recording everything, ask whether a plant grows better near a particular window. That gives the journal a clear purpose.'),
    ('Change one condition', 'Move the plant, then leave the watering and potting mix alone for a while. Too many simultaneous changes make the result hard to interpret.'),
    ('Make the next decision', 'At the end of several weeks, compare what you expected with new leaves, stems and soil conditions. Keep the change only if the plant is actually doing well.')],
    'Your notes do not need an app. A dated photo and a sentence in a notebook are often enough.')]
 },
 'night-sky': {
  'tonight.html': [
   ('A first observation from your own neighbourhood', 'THE EVENING PRACTICE', [
    ('Choose a familiar viewpoint', 'A courtyard or an open spot near home can be sufficient. Prioritise safe access and an unobstructed portion of sky over travelling far away.'),
    ('Look before naming', 'Notice how bright points differ from one another and where the brightest objects sit above the horizon. Try describing what you see without immediately consulting a chart.'),
    ('Record a direction', 'Use a compass or a familiar landmark to fix one direction. Return to the same place later and notice how the arrangement appears to shift.')],
    'One reliable observation is more valuable than a long list of objects you could not locate with confidence.'),
   ('How to make fifteen minutes under the sky count', 'A SHORT FIELD SESSION', [
    ('Check the conditions', 'Cloud cover, nearby lighting and the phase of the Moon shape what is visible. A bright night is not a failure; simply choose an easy target.'),
    ('Let the scene settle', 'Put away the bright phone screen and wait until your eyes become comfortable in the dark. There is no need to rush from star to star.'),
    ('Finish with a note', 'Write the time, rough direction and one pattern you recognised. A tiny sketch may be easier to remember than a paragraph of names.')],
    'Dress for standing still. A short comfortable session can be more productive than a long cold one.')],
  'moon.html': [
   ('Following the lunar month from home', 'PHASES IN THE SKY', [
    ('Watch the illuminated edge', 'The bright portion changes gradually as our viewing angle to the Sun-lit half of the Moon changes. Its outline tells a story over successive nights.'),
    ('Notice the position', 'The Moon appears at different times and places as its orbit progresses. The same clock hour will not always reveal it in the same part of the sky.'),
    ('Try a sequence of sketches', 'Draw a simple circle each clear evening and shade the dark portion. Put the sketches in date order to reveal the rhythm.')],
    'A thin crescent can be easier to notice when you know when and where to look; check a reliable local sky calendar.'),
   ('Look closely at the lunar landscape', 'BINOCULAR FIELD NOTES', [
    ('Start without magnification', 'Identify the overall phase and a few large light and dark areas. These broad markings remain recognisable as your observing skills improve.'),
    ('Find the terminator', 'The boundary between lit and unlit terrain often shows long shadows. Comparing its position on different evenings reveals fresh detail.'),
    ('Use a steady view', 'Rest your elbows or support binoculars to make smaller features easier to see. Never look at the Sun through unfiltered optics.')],
    'You do not need a map of every crater. Recognising a few familiar features is a good beginning.')],
  'constellations.html': [
   ('A practical way to learn star patterns', 'FINDING YOUR WAY', [
    ('Start with a large shape', 'Look for two or three bright stars that form an obvious line or triangle. Use their relative spacing as your first guide.'),
    ('Use a local chart', 'The sky visible from your home depends on latitude, date and time. A location-specific chart helps avoid searching for objects below the horizon.'),
    ('Add one neighbour', 'Once a pattern is familiar, trace toward a nearby star group instead of learning the entire sky at once. Return on another night to confirm it.')],
    'A constellation is a region on a map of the sky; familiar star drawings are convenient guides rather than physical connections.'),
   ('Why the sky does not look the same each season', 'SEASONAL PATTERNS', [
    ('Think about Earth’s orbit', 'As our planet travels around the Sun, the night side points toward different backgrounds of stars during the year.'),
    ('Account for the hour', 'The sky appears to rotate during the night. A chart prepared for one time may not match an observation many hours later.'),
    ('Compare sketches', 'Draw the brightest stars above a chosen building or tree line. Months later, use the same landmark to notice how the sky has changed.')],
    'Clouds and streetlights limit how many stars you can see, but the brightest patterns can still be useful landmarks.')],
  'equipment.html': [
   ('A useful observing kit fits in a small bag', 'FIELD ESSENTIALS', [
    ('Dress for stillness', 'An extra layer, a warm drink and a stable place to sit can make an evening more pleasant than an expensive piece of equipment.'),
    ('Bring a simple chart', 'Paper notes avoid bright screens and dead batteries. A dim red torch may be helpful for reading without destroying your dark adaptation.'),
    ('Choose optics later', 'After a few evenings, decide whether binoculars would help with the objects you actually enjoy looking at.')],
    'Make observing easy to repeat. The best kit is the one you will comfortably carry outside.'),
   ('What matters more than a telescope specification', 'BUY LESS, OBSERVE MORE', [
    ('Stability before power', 'A shaky high-magnification view can be less useful than steady binoculars. Support and ease of handling deserve attention.'),
    ('Match the tool to the target', 'Wide fields are pleasant for large star groups; detailed lunar views call for different optics. One instrument cannot optimise every kind of viewing.'),
    ('Avoid rushed upgrades', 'Get to know the limits of your current equipment before buying something new. Weather and light pollution may be the real constraints.')],
    'Never point any unfiltered optical device toward the Sun, even briefly.')]
 },
 'kitchen': {
  'recipes.html': [
   ('Three dinners built from a few staples', 'MIDWEEK COOKING', [
    ('White beans and spinach', 'Warm drained beans with sliced garlic and a little olive oil. Stir through spinach until wilted, finish with lemon and serve over warm grains or toast.'),
    ('A tray of spiced vegetables', 'Toss chopped roots or squash with oil, paprika and salt. Roast until tender, turning once, then add yogurt or a squeeze of lemon at the table.'),
    ('Quick tomato chickpeas', 'Gently cook onion in oil, add canned tomatoes and chickpeas, and simmer until the sauce thickens. Taste and finish with herbs or a spoon of yogurt.')],
    'Use a thermometer when cooking meat or poultry; visual colour alone does not establish safe doneness.'),
   ('Simple meals for a small table', 'FLEXIBLE RECIPES', [
    ('Herb omelette with greens', 'Wilt a handful of greens, add beaten eggs and chopped herbs, and cook gently until set to your preference. Serve with bread and a crisp salad.'),
    ('Warm lentil salad', 'Combine cooked lentils with roasted or sautéed vegetables, mustard and a little vinegar. Taste carefully and add herbs before serving.'),
    ('Pantry pasta with tomatoes', 'Cook pasta until tender, reserve some cooking water and toss with a simple tomato-garlic sauce. Add enough water to make the sauce coat the pasta.')],
    'Choose quantities based on appetite and the ingredients available, and refrigerate leftovers promptly.')],
  'pantry.html': [
   ('A cupboard built for meals you actually make', 'A PRACTICAL PANTRY', [
    ('Begin with a few repeat meals', 'List the dishes you cook most often and identify the shelf-stable ingredients they share. Those are the items worth keeping in reserve.'),
    ('Keep flavor tools simple', 'A small collection of salt, a versatile oil, vinegar and familiar spices can do more than a cupboard crowded with rarely used jars.'),
    ('Make restocking visible', 'Put older packets toward the front and note what is running low. A quick glance should tell you whether tonight’s plan is possible.')],
    'A useful pantry is personal; it should reflect the food you like eating, not an idealised shopping list.'),
   ('Make shelf space work harder', 'STORAGE AND ROUTINE', [
    ('Group by use', 'Keep grains and legumes close together, baking supplies elsewhere, and everyday seasonings where you can reach them easily.'),
    ('Respect storage advice', 'Store dry ingredients sealed and away from moisture, and follow labels for foods that need refrigeration once opened.'),
    ('Plan one flexible fallback', 'Keep ingredients for a familiar quick supper so a late evening does not demand a special shopping trip.')],
    'Good storage is less about buying containers than about being able to see and use what you already own.')],
  'techniques.html': [
   ('Three small skills that improve everyday cooking', 'FROM HEAT TO PLATE', [
    ('Dry before browning', 'A wet surface steams before it can brown. Pat suitable ingredients dry and give the pan enough room for hot air and moisture to escape.'),
    ('Taste before adding more salt', 'Food changes as liquid evaporates. Season moderately in stages, then taste the finished dish before reaching for another pinch.'),
    ('Rest and serve deliberately', 'A short rest can help some cooked foods settle before cutting. Use safe temperatures for perishable ingredients and serve promptly.')],
    'Try improving one familiar recipe with a single technique rather than changing every ingredient at once.'),
   ('Cooking well is a sequence of choices', 'OBSERVE THE PAN', [
    ('Choose the right heat', 'A gentle simmer suits delicate soups, while browning needs adequate heat and space. Adjust the pan to the goal rather than using maximum heat by habit.'),
    ('Mind moisture', 'Water in vegetables and sauces changes texture. Cook uncovered when reducing liquid; cover the pan when retaining steam is useful.'),
    ('Finish with balance', 'At the end, check for salt, acidity and texture. One small correction often makes a larger difference than extra ingredients.')],
    'A timer is useful, but the smell, sound and appearance of food also provide information as it cooks.')],
  'seasons.html': [
   ('Seasonal cooking without a strict calendar', 'WHAT LOOKS GOOD NOW', [
    ('Begin at the market', 'Choose produce for freshness and condition rather than relying on a fixed date. Local growing seasons differ widely across regions.'),
    ('Match the method', 'Tender vegetables often suit quick cooking, while denser roots benefit from roasting or longer simmering.'),
    ('Keep one good habit', 'Write down a seasonal combination you enjoyed. Next year you can return to it when the ingredients are at their best.')],
    'A local market stall can tell you more about today’s produce than a generic seasonal infographic.'),
   ('A seasonal table can stay simple', 'INGREDIENTS FIRST', [
    ('Use freshness as a guide', 'A crisp vegetable may need little more than a short cook and a good dressing. Taste an ingredient before deciding on the recipe.'),
    ('Build around what lasts', 'Beans, grains and dry pasta make flexible foundations; add the fresh produce that looks best when you shop.'),
    ('Store surplus safely', 'If you have more than you can use, freeze suitable foods promptly and follow tested preservation instructions for anything kept longer.')],
    'Let ingredient quality lead and keep your technique uncomplicated.')]
 }
}


# Independently written small front-page editorial sections; no timestamps,
# imaginary authors, live claims, or remotely fetched material.
HOME_EDITORIAL = {
 'botanical': [
  ('Good care is mostly good attention.', 'Learn the basics in a way that works with your space rather than against it.', 'A new leaf can tell you more than a complicated schedule.'),
  ('Let the room set the routine.', 'Notice the particular light, temperature and pace of growth around your plants before choosing what to change.', 'Small observations make a useful growing habit.'),
  ('Houseplants do not read calendars.', 'The pot, the season and the window help explain more than a fixed watering or feeding reminder.', 'Start with the conditions you can actually see.'),
  ('A growing collection of ordinary notes.', 'These short guides focus on practical adjustments that fit real homes and familiar plants.', 'A little patience belongs in every pot.')],
 'night-sky': [
  ('What should you notice first?', 'You do not need an expensive telescope to learn your sky. Begin with orientation, give your eyes time and return to the same place.'),
  ('Begin with a few bright landmarks.', 'Find one recognisable pattern, learn its direction and make a second observation before trying to memorise the whole sky.'),
  ('Make the familiar sky your map.', 'A regular view from home can teach seasonal changes just as well as an occasional journey to a dark landscape.'),
  ('Observation comes before equipment.', 'Spend a short, comfortable evening identifying what is visible; let your interests guide any later choice of tools.')],
 'kitchen': [
  ('Let the market set the rhythm.', 'There is always something worth cooking well, no matter the month.'),
  ('Good meals start with ordinary ingredients.', 'A handful of flexible staples and one fresh addition can be the beginning of dinner.'),
  ('Cook what is at its best today.', 'Choose ingredients for flavour and condition, then let a simple method do the work.'),
  ('Keep one reliable supper in mind.', 'A short list of familiar dishes can make a busy evening feel less complicated.')]
}


def esc(value):
    return html.escape(str(value), quote=True)


def nav(theme, current):
    return ''.join(f'<a href="{esc(path)}"'+(' aria-current="page"' if path==current else '')+f'>{esc(label)}</a>' for path,label in DATA[theme]['pages'])


def botanical_shell(brand, current, body, palette, headline=None, description=None):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="{esc(description or 'Independent illustrated notes on indoor plants, light, watering and everyday growing.')}"><meta name="theme-color" content="{palette[0]}"><title>{esc(headline or dict(DATA["botanical"]["pages"])[current])} | {esc(brand)}</title><link rel="stylesheet" href="site.css"><link rel="icon" type="image/svg+xml" href="favicon.svg"><link rel="icon" type="image/x-icon" href="favicon.ico"></head><body class="plant-body"><a class="skip" href="#main">Skip to content</a><div class="plant-wrap"><header class="plant-top"><a href="index.html" class="plant-logo"><span class="plant-logo-mark">✳</span><span>{esc(brand)}</span></a><nav aria-label="Main navigation">{nav('botanical',current)}</nav><span class="plant-edition">A field guide for home</span></header><main id="main">{body}</main><footer class="plant-footer"><div><strong>{esc(brand)}</strong><p>Independent notes for patient indoor growing.</p></div><span>Observe carefully. Change one thing at a time.</span><a href="field-notes.html">Field notes →</a></footer></div></body></html>'''


def sky_shell(brand,current,body,palette,headline=None,description=None):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="{esc(description or 'Original accessible guides to observing stars, the Moon, and the night sky.')}"><meta name="theme-color" content="{palette[1]}"><title>{esc(headline or dict(DATA["night-sky"]["pages"])[current])} | {esc(brand)}</title><link rel="stylesheet" href="site.css"><link rel="icon" type="image/svg+xml" href="favicon.svg"><link rel="icon" type="image/x-icon" href="favicon.ico"></head><body class="sky-body"><a class="skip" href="#main">Skip to content</a><div class="sky-layout"><aside class="sky-side"><a class="sky-wordmark" href="index.html"><span class="sky-sigil">✧</span>{esc(brand)}</a><div class="sky-side-note">INDEPENDENT FIELD GUIDE <span>•</span> ALL SEASONS</div><nav aria-label="Main navigation">{nav('night-sky',current)}</nav><p class="sky-side-bottom">No equipment required to begin.<br>Just a clear view and curiosity.</p></aside><div class="sky-main"><div class="sky-toolbar"><span>AN ATLAS FOR CURIOUS OBSERVERS</span><span class="sky-coordinates">RA • DEC • HORIZON</span></div><main id="main">{body}</main><footer class="sky-footer"><span>{esc(brand)}</span><p>Take only observations. Leave no trace.</p><a href="tonight.html">Begin observing →</a></footer></div></div></body></html>'''


def kitchen_shell(brand,current,body,palette,headline=None,description=None):
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="description" content="{esc(description or 'Original simple recipes, pantry advice and everyday home cooking techniques.')}"><meta name="theme-color" content="{palette[1]}"><title>{esc(headline or dict(DATA["kitchen"]["pages"])[current])} | {esc(brand)}</title><link rel="stylesheet" href="site.css"><link rel="icon" type="image/svg+xml" href="favicon.svg"><link rel="icon" type="image/x-icon" href="favicon.ico"></head><body class="kitchen-body"><a class="skip" href="#main">Skip to content</a><div class="kitchen-frame"><div class="kitchen-pretop"><span>GOOD FOOD / EVERY DAY</span><span>THE HOME COOK’S READER</span></div><header class="kitchen-head"><a href="index.html" class="kitchen-brand">{esc(brand)}<i>✳</i></a><nav aria-label="Main navigation">{nav('kitchen',current)}</nav></header><main id="main">{body}</main><footer class="kitchen-foot"><div><strong>{esc(brand)}</strong><p>Keep it simple. Make it good.</p></div><span>Recipes and notes for an everyday table.</span><a href="recipes.html">Browse recipes →</a></footer></div></body></html>'''


def make_home(theme, brand, copy, palette, front_index=None):
    h,l,k=map(esc,copy)
    edits = HOME_EDITORIAL[theme]
    if front_index is None:
        front_index=secrets.randbelow(len(edits))
    if not isinstance(front_index,int) or not 0 <= front_index < len(edits):
        raise ValueError('invalid front-page edition')
    editorial=edits[front_index]
    if theme=='botanical':
        body=f'''<section class="plant-hero"><div class="plant-hero-text"><span class="plant-overline">{k} / A SMALL INDEPENDENT JOURNAL</span><h1>{h}</h1><p class="lead">{l}</p><div class="hero-links"><a class="plant-button" href="light.html">Find your light <span>↗</span></a><a class="plant-text-link" href="field-notes.html">Read field notes →</a></div><p class="plant-hero-note"><b>01 / 04</b> Simple care. Thoughtful observation.</p></div><figure class="plant-hero-art"><img src="illustration.svg" alt="Original botanical illustration of leaves and delicate stems"><figcaption>AN ILLUSTRATED STUDY IN GREEN</figcaption></figure></section><div class="plant-rule"><span>THE PRACTICAL NOTEBOOK</span><span>HOUSEPLANTS & HOME</span></div><section class="plant-section"><div class="section-intro"><span class="plant-overline">GROWING, WITHOUT GUESSWORK</span><h2>Good care is mostly good attention.</h2><p>Learn the basics in a way that works with your space rather than against it.</p></div><div class="plant-cards"><a href="light.html"><span>01 / LIGHT</span><h3>A better place by the window</h3><p>Read a room before moving every plant toward the brightest corner.</p><b>Explore the guide ↗</b></a><a href="watering.html"><span>02 / WATER</span><h3>Water the soil, not the date</h3><p>Use the pot and conditions to decide when it is time.</p><b>Explore the guide ↗</b></a><a href="plants.html"><span>03 / PLANTS</span><h3>Meet familiar houseplants</h3><p>Five useful starting points, without one-size-fits-all rules.</p><b>Explore the guide ↗</b></a></div></section><section class="plant-quote"><span>FIELD NOTE / 001</span><blockquote>“A new leaf can tell you more than a complicated schedule.”</blockquote><a href="field-notes.html">Keep a four-week journal →</a></section>'''
        original=HOME_EDITORIAL['botanical'][0]
        for before,after in zip(original,editorial):
            body=body.replace(before,esc(after),1)
        return botanical_shell(brand,'index.html',body,palette)
    if theme=='night-sky':
        body=f'''<section class="sky-hero"><div class="sky-hero-copy"><span class="sky-kicker">{k} / VOL. 01</span><h1>{h}</h1><p class="sky-lede">{l}</p><div class="sky-actions"><a class="sky-action" href="tonight.html">Start observing <span>↗</span></a><a class="sky-link" href="moon.html">A note on the Moon →</a></div></div><div class="sky-orbit"><img src="illustration.svg" alt="Original vector artwork of lunar orbit and a field of stars"><div class="sky-art-corner">CHART 001 / NOT TO SCALE</div></div></section><section class="sky-now"><div><span>LOOK UP</span><h2>What should you notice first?</h2><p>You do not need an expensive telescope to learn your sky. Begin with orientation, give your eyes time and return to the same place.</p></div><a href="tonight.html">An evening's first steps ↗</a></section><section class="sky-cards"><a href="moon.html"><span>02 / OUR NEAREST NEIGHBOR</span><h3>Follow the changing Moon</h3><p>Learn phases and look for lunar detail without chasing magnification.</p><strong>Read the note →</strong></a><a href="constellations.html"><span>03 / FIND YOUR BEARINGS</span><h3>Patterns after dark</h3><p>A simple route into constellations, seasons and familiar landmarks.</p><strong>Read the note →</strong></a><a href="equipment.html"><span>04 / FIELD KIT</span><h3>Begin with less</h3><p>The best first tool is time spent looking; binoculars can come later.</p><strong>Read the note →</strong></a></section>'''
        original=HOME_EDITORIAL['night-sky'][0]
        for before,after in zip(original,editorial):
            body=body.replace(before,esc(after),1)
        return sky_shell(brand,'index.html',body,palette)
    body=f'''<section class="kitchen-hero"><div class="kitchen-hero-copy"><span class="kitchen-label">{k} <span>ISSUE N° 01</span></span><h1>{h}</h1><p>{l}</p><div class="kitchen-hero-buttons"><a href="recipes.html" class="kitchen-button">See the recipes ↗</a><a href="techniques.html" class="kitchen-outline">Learn a technique →</a></div><div class="kitchen-stamp">COOK • TASTE • ADJUST</div></div><div class="kitchen-hero-picture"><img src="illustration.svg" alt="Original illustrated serving bowl with herbs and vegetables"><span>ILLUSTRATED FROM THE HOME TABLE / 01</span></div></section><section class="kitchen-subhead"><span>THREE THINGS TO READ FIRST</span><p>Real ingredients. Useful habits. No unnecessary fuss.</p></section><section class="kitchen-stories"><a href="recipes.html"><span>01 / AT THE TABLE</span><h2>Simple meals for ordinary days.</h2><p>Three flexible recipes that welcome small changes.</p><b>Read recipes ↗</b></a><a href="pantry.html"><span>02 / THE CUPBOARD</span><h2>Make more with what you have.</h2><p>A thoughtful pantry keeps good food close at hand.</p><b>Open the pantry ↗</b></a><a href="techniques.html"><span>03 / LITTLE SKILLS</span><h2>The details that make dinner.</h2><p>Heat, seasoning and timing are worth understanding.</p><b>Learn techniques ↗</b></a></section><section class="kitchen-bottom"><div><span>THIS SEASON</span><h2>Let the market set the rhythm.</h2><p>There is always something worth cooking well, no matter the month.</p></div><a href="seasons.html">Explore the seasonal notes ↗</a></section>'''
    original=HOME_EDITORIAL['kitchen'][0]
    for before,after in zip(original,editorial):
        body=body.replace(before,esc(after),1)
    return kitchen_shell(brand,'index.html',body,palette)


def make_article(theme, brand, page, palette, note_index, article_index=None):
    options = [ARTICLE[theme][page], *ARTICLE_ALTERNATES[theme][page]]
    if article_index is None:
        article_index = secrets.randbelow(len(options))
    if not isinstance(article_index, int) or not 0 <= article_index < len(options):
        raise ValueError('invalid article edition')
    title,kicker,parts,aside = options[article_index]
    parts = [*parts, EXTRA_NOTES[theme][page][note_index]]
    if theme=='botanical':
        sections=''.join(f'<section><span class="plant-chapter">0{i}</span><div><h2>{esc(h)}</h2><p>{esc(p)}</p></div></section>' for i,(h,p) in enumerate(parts,1))
        body=f'''<div class="plant-article-head"><a href="index.html">← Back to the journal</a><span>{esc(kicker)}</span><h1>{esc(title)}</h1><p>Practical notes for taking the next sensible step.</p></div><div class="plant-article-grid"><article>{sections}</article><aside><span>THE SMALL OBSERVATION</span><p>{esc(aside)}</p><a href="field-notes.html">Keep field notes →</a></aside></div><div class="plant-article-close"><p>Curious about another topic?</p><a href="watering.html">Watering</a><a href="light.html">Light</a><a href="plants.html">Plants</a></div>'''
        return botanical_shell(brand,page,body,palette,title,parts[0][1])
    if theme=='night-sky':
        sections=''.join(f'<section><div class="sky-article-num">0{i} / 0{len(parts)}</div><h2>{esc(h)}</h2><p>{esc(p)}</p></section>' for i,(h,p) in enumerate(parts,1))
        body=f'''<div class="sky-article-hero"><span>{esc(kicker)} / OBSERVER'S NOTES</span><h1>{esc(title)}</h1><p>Everything here can be practiced a little at a time, from wherever you can see the sky.</p></div><div class="sky-article-layout"><article>{sections}</article><aside><span>FIELD REMINDER</span><p>{esc(aside)}</p><div class="sky-aside-mark">✶ ✧ ✦</div></aside></div><div class="sky-next"><a href="tonight.html">First evening →</a><a href="moon.html">The Moon →</a><a href="constellations.html">Star patterns →</a></div>'''
        return sky_shell(brand,page,body,palette,title,parts[0][1])
    sections=''.join(f'<section class="kitchen-step"><div class="kitchen-step-num">{i:02d}</div><div><h2>{esc(h)}</h2><p>{esc(p)}</p></div></section>' for i,(h,p) in enumerate(parts,1))
    body=f'''<div class="kitchen-article-hero"><a href="index.html">← The journal</a><span>{esc(kicker)}</span><h1>{esc(title)}</h1><p>Written for real kitchens and real everyday schedules.</p></div><div class="kitchen-article"><article>{sections}</article><aside><span>ONE THING TO REMEMBER</span><p>{esc(aside)}</p><div class="kitchen-small-art">✳</div></aside></div><div class="kitchen-article-end"><span>KEEP COOKING</span><a href="recipes.html">Recipes →</a><a href="pantry.html">Pantry →</a><a href="techniques.html">Techniques →</a></div>'''
    return kitchen_shell(brand,page,body,palette,title,parts[0][1])


def svg_art(theme, variant, color, bg, soft, secondary):
    if theme=='botanical':
        # Botanical leaves are drawn with native SVG paths; each variant changes the arrangement.
        branches=[]
        for i in range(5+variant):
            x=125+i*62
            h=115+(i*31+variant*17)%130
            tip=420-h
            branches.append(f'<path d="M{x} 451 Q{x-34} {365-h/6:.1f} {x-17} {tip}" fill="none" stroke="{color}" stroke-width="3"/>'
                f'<path d="M{x-18} {tip+32} C{x-115} {tip-5}, {x-98} {tip+118}, {x-21} {tip+108} C{x+12} {tip+85}, {x+12} {tip+51}, {x-18} {tip+32}Z" fill="{soft}" stroke="{color}" stroke-width="2"/>'
                f'<path d="M{x-13} {tip+88} C{x+80} {tip+52}, {x+84} {tip+153}, {x-4} {tip+152} C{x-36} {tip+145}, {x-31} {tip+105}, {x-13} {tip+88}Z" fill="{secondary}" fill-opacity=".32" stroke="{color}" stroke-width="2"/>')
        shape=''.join(branches)
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560"><rect width="720" height="560" rx="8" fill="{bg}"/><g opacity=".32" stroke="{color}" fill="none"><circle cx="360" cy="284" r="219"/><circle cx="360" cy="284" r="168"/><path d="M72 284H650M360 35V535" stroke-dasharray="4 10"/></g><ellipse cx="350" cy="465" rx="220" ry="21" fill="{soft}"/><g>{shape}</g><path d="M105 455Q358 480 610 455" stroke="{color}" stroke-width="5" fill="none"/></svg>'''
    if theme=='night-sky':
        import math
        star=[]
        for i in range(57):
            x=38+((i*109+variant*137)%636);y=30+((i*67+variant*71)%450)
            rr=(1,1.4,2)[i%3]
            star.append(f'<circle cx="{x}" cy="{y}" r="{rr}" fill="{color}" opacity="{.18+(i%5)*.1:.2f}"/>')
        phi=(variant*19)-26
        return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560"><rect width="720" height="560" fill="{bg}"/><g>{''.join(star)}</g><circle cx="367" cy="271" r="195" stroke="{color}" stroke-opacity=".35" fill="none"/><circle cx="367" cy="271" r="148" stroke="{secondary}" stroke-opacity=".3" fill="none" stroke-dasharray="3 8"/><path d="M367 38V516M133 271H606" stroke="{secondary}" stroke-opacity=".24"/><g transform="rotate({phi} 367 271)"><circle cx="367" cy="271" r="93" fill="{color}"/><path d="M367 178a93 93 0 0 0 0 186a54 93 0 0 1 0-186" fill="{soft}"/></g><g stroke="{secondary}" stroke-width="2" opacity=".7"><path d="M92 91L186 119 212 58 316 103" fill="none"/><path d="M503 387L588 423 648 377" fill="none"/></g></svg>'''
    # editorial kitchen bowl illustration
    herbs=[]
    for i in range(8+variant):
        x=254+(i*43%230);y=252+(i*31%75)
        herbs.append(f'<ellipse cx="{x}" cy="{y}" rx="{23+(i%3)*5}" ry="11" transform="rotate({(i*47)%170} {x} {y})" fill="{secondary}" opacity=".80"/>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="720" height="560" viewBox="0 0 720 560"><rect width="720" height="560" fill="{bg}"/><circle cx="367" cy="272" r="204" fill="none" stroke="{color}" opacity=".24"/><circle cx="367" cy="272" r="165" fill="none" stroke="{color}" opacity=".15"/><ellipse cx="372" cy="440" rx="226" ry="33" fill="{color}" opacity=".12"/><path d="M170 270Q180 471 370 464Q559 470 568 270" fill="{soft}" stroke="{color}" stroke-width="5"/><ellipse cx="369" cy="272" rx="200" ry="86" fill="{bg}" stroke="{color}" stroke-width="6"/><ellipse cx="369" cy="273" rx="176" ry="64" fill="{color}" opacity=".15"/>{''.join(herbs)}<circle cx="321" cy="265" r="23" fill="{color}" opacity=".8"/><circle cx="415" cy="290" r="18" fill="{color}" opacity=".7"/><circle cx="382" cy="247" r="15" fill="{color}" opacity=".55"/><path d="M586 124L611 392" stroke="{color}" stroke-width="9" stroke-linecap="round"/><path d="M600 129L625 396" stroke="{color}" stroke-width="9" stroke-linecap="round" opacity=".48"/></svg>'''


def make_ico(theme, palette):
    """Render a 32-pixel Windows icon (BMP-in-ICO), stdlib only."""
    import struct
    w = h = 32
    def rgb(hexval):
        return tuple(bytes.fromhex(hexval.lstrip('#')))
    ink,bg,soft,accent=map(rgb,palette)
    pixels=[]
    for y in range(h-1,-1,-1):
        for x in range(w):
            dx,dy=x-15.5,y-15.5
            color=bg
            if theme=='botanical':
                # Leaf and vein.
                leaf=((dx+2)*0.85+(dy+1)*0.55)**2/107 + ((dy+1)*0.85-(dx+2)*0.55)**2/42 < 1
                if leaf: color=ink
                if abs((x+y)-30)<1.4 and 9<x<25:color=accent
            elif theme=='night-sky':
                if dx*dx+dy*dy<125 and (dx-5)**2+(dy+5)**2>110:color=ink
                if (x-25)**2+(y-7)**2<5:color=accent
            else:
                r2=dx*dx+dy*dy
                if 70<r2<105:color=ink
                elif 20<r2<27:color=accent
                if x in (3,28) and 8<y<25:color=ink
            pixels.extend((*color[::-1],255))
    dib=struct.pack('<IiiHHIIiiII',40,w,h*2,1,32,0,4*w*h,0,0,0,0)
    image=dib+bytes(pixels)+bytes(((w+31)//32)*4*h)
    return struct.pack('<HHH',0,1,1)+struct.pack('<BBBBHHII',w,h,0,0,1,32,len(image),22)+image


def generate(out, theme=None, selection=None):
    theme = theme or secrets.choice(list(DATA))
    d = DATA[theme]
    def choice(values, index):
        if index is None:
            return secrets.choice(values)
        if not isinstance(index, int) or not 0 <= index < len(values):
            raise ValueError('invalid variant index')
        return values[index]
    spec = selection or {}
    brand=choice(d['brands'],spec.get('brand'))
    palette=choice(d['colors'],spec.get('palette'))
    copy=choice(d['copy'],spec.get('copy'))
    art=spec.get('art') if 'art' in spec else secrets.randbelow(5)
    if not isinstance(art, int) or not 0 <= art < 5:
        raise ValueError('invalid art index')
    out=Path(out)
    if out.exists():
        raise FileExistsError(f'refusing to overwrite {out}')
    out.mkdir(parents=True)
    for page,_ in d['pages']:
        content=make_home(theme,brand,copy,palette) if page=='index.html' else make_article(theme,brand,page,palette,secrets.randbelow(4))
        (out/page).write_text(content+'\n',encoding='utf-8')
    template=(HERE/'templates'/theme/'site.css').read_text(encoding='utf-8')
    for label,value in zip(['INK','BG','SOFT','ACCENT'],palette):
        template=template.replace('{{'+label+'}}',value)
    (out/'site.css').write_text(template,encoding='utf-8')
    (out/'illustration.svg').write_text(svg_art(theme,art,*palette),encoding='utf-8')
    ink,bg,soft,accent=palette
    # Separate graphic identities for the three genuinely different publications.
    glyphs = {
        'botanical': f'<path d="M18 45C15 29 27 18 48 16C49 35 39 49 18 45Z" fill="{soft}" stroke="{ink}" stroke-width="3"/><path d="M17 49C22 35 32 29 46 20" stroke="{ink}" stroke-width="2" fill="none"/>',
        'night-sky': f'<path d="M38 14A22 22 0 1 0 48 43A20 20 0 0 1 38 14Z" fill="{ink}"/><circle cx="44" cy="16" r="3" fill="{accent}"/><path d="M47 5v6m-3-3h6" stroke="{ink}" stroke-width="2"/>',
        'kitchen': f'<circle cx="32" cy="32" r="22" fill="{soft}" stroke="{ink}" stroke-width="3"/><circle cx="32" cy="32" r="13" fill="none" stroke="{accent}" stroke-width="2"/><path d="M8 18v29m-3-29v12m6-12v12m46-12v29" fill="none" stroke="{ink}" stroke-width="3" stroke-linecap="round"/>',
    }
    icon=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="13" fill="{bg}"/>{glyphs[theme]}</svg>'
    (out/'favicon.svg').write_text(icon+'\n',encoding='utf-8')
    (out/'favicon.ico').write_bytes(make_ico(theme,palette))
    not_found = {
        'botanical': ('Page not found', 'That note is not in this journal.', 'Browse the plant-care guides or return to the main page.'),
        'night-sky': ('Lost your bearings?', 'We cannot find that sky note.', 'Return to the overview and choose an observation guide.'),
        'kitchen': ('This page is missing', 'Nothing is cooking at this address.', 'Browse our recipes and kitchen notes from the home page.'),
    }
    title, heading, detail = not_found[theme]
    (out/'404.html').write_text((
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="robots" content="noindex">'
        f'<title>{esc(title)} | {esc(brand)}</title>'
        '<link rel="stylesheet" href="/site.css">'
        '<link rel="icon" type="image/svg+xml" href="/favicon.svg">'
        '</head><body><main class="notfound"><span>404 / NOT FOUND</span>'
        f'<h1>{esc(heading)}</h1><p>{esc(detail)}</p>'
        '<a href="/">Return to the home page →</a></main></body></html>\n'),encoding='utf-8')
    (out/'robots.txt').write_text(f'# {brand}\nUser-agent: *\nDisallow:\n',encoding='utf-8')
    # Private build manifest. Never publish this with the public static files.
    return dict(theme=theme,brand=brand,palette_index=d['colors'].index(palette),
                brand_index=d['brands'].index(brand),copy_index=d['copy'].index(copy),art_index=art,
                public_file_count=len(list(out.iterdir())))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',required=True,help='new empty destination directory')
    p.add_argument('--theme',choices=DATA.keys(),help='optional fixed design for demonstration')
    p.add_argument('--brand-index',type=int)
    p.add_argument('--palette-index',type=int)
    p.add_argument('--copy-index',type=int)
    p.add_argument('--art-index',type=int)
    args=p.parse_args()
    spec={k:v for k,v in dict(brand=args.brand_index,palette=args.palette_index,
            copy=args.copy_index,art=args.art_index).items() if v is not None}
    result=generate(args.output,args.theme,spec)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
