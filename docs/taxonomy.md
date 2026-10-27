# Names

What every kind of thing in a game's data is called in the viewer, how one
is numbered and pointed at, where each kind lives, and how the kinds link
to one another. The same names are used everywhere: the rail, the tabs,
the lists, the cards, the Inspector, the links, export file names and the
viewer's own code.

This page is the reference the code is held to, as the decoders' inventory
is. The links table below says which links the code makes and which it does
not yet.

Why it is needed: the viewer is to link anything to anything. Pick a person
on a map and see who they are, what they say, their voice and where else
they stand; pick a fight and hear what it plays; pick an item and see which
chests hold it, which shops sell it and which monsters drop it. When this
page was first written one link existed (a map's or a fight's music), each
tab named its things its own way, numbers were written five ways, and words
such as *set*, *row*, *event* and *scene* each meant four or five things. A link needs both its
ends to agree on what a thing is and what it is called.

## The rule

1. **Simple to complex.** Everywhere in the viewer, what a player knows
   comes first and how the game does it comes after: the plain name before
   the code's, the plain number before the hex, the picture or the sound
   before the bytes, a tab's fan view before its technical views, the fans'
   tabs before the disc's. Nothing technical is dropped; it moves to the
   end, where whoever wants it finds it — and *Advanced* mode puts it
   first (see *Two modes*).
2. **The game's word first, then the fans', then the code's.** Where the
   game's own menus have a word for a kind, the viewer uses it; where they
   do not, the word fans use; where fans have none, the code's — the
   developers' own first, then the decompilation's register
   (eternal-silver-sssc-decomp, `docs/naming.md`). The code's name always
   travels with the thing: every card's and the Inspector's extended info
   gives it, and every citation uses it (`StoryBitSet (0x800576EC)`), so a
   reader can go from the viewer to the decompilation and back.
3. **One name for each kind, and no word for two kinds.** A word that
   would mean two things is qualified (*map monster*, *monster group*,
   *tile change*) or not used (see *Words retired*).
4. **Every thing has one reference: its kind and its number, in decimal**
   (`map 21`, `battle 46`, `message 11/37`), written the same in a list, a
   card, a link and an export's file name, and independent of any tab, view
   or list order. A sound effect of a place's own is numbered by its sound
   bank, then its number (`sound effect 300/131`), as the same number is
   another sound in another place; one heard everywhere or in battle by its
   number alone (`sound effect 13`) (ruled 2026-10-26). The extended info gives the same number in hex and as
   the specification writes it (`map 0x15`). Addresses and offsets are hex
   wherever they appear; they are never references.
5. **The app's words and the game's never cross.** *Tab, view, list, entry,
   card, panel, Inspector, transport, clip, version, tick* are the app's;
   none names a game thing, and no game word names a part of the app.
6. **A link exists only where the game's code makes it,** and its card says
   which function does, as every decoder already says what proves its
   format.

## Two modes

One viewer, two ways in. **Fan mode** is for exploring the game: its rail
is laid out the way a fan wiki is, and shows the tabs a player's things
live in. **Advanced mode** is for looking under the hood: its rail holds
every tab, the disc's storage too, grouped by the kind of asset. The
switch is at the foot of the rail, and the viewer remembers it.

Both modes are the same tabs, the same names, the same cards and the same
links; only the arrangement and what shows first differ:

| | Fan mode | Advanced mode |
|---|---|---|
| the rail | six groups of the game (below), 17 tabs | six groups by kind of asset (below), all 24 tabs |
| a tab opens on | its fan view | its technical view, where it has one |
| a card's and the Inspector's extended info | folded | open |
| numbers in lists and titles | decimal: *map 21* | decimal, hex beside: *map 21 (0x15)* |
| names | the fan words | the same fan words; the code's in extended info |

A thing whose home is only in Advanced mode — a resource, a sound bank, a
string — still shows in a fan-mode card's extended info, as *Open in
Resources (Advanced)*; following it switches mode.

## The tabs

Every tab, what it holds, its views simple to complex (*technical* marks
the view Advanced mode opens on), and its group in each mode.

| tab | holds | views | Fan mode | Advanced mode |
|---|---|---|---|---|
| **Maps** | every map, by Overworld / Towns / Dungeons | the live map (Raw \| In game), its panels | World | Graphics |
| **Characters** | the characters, the party's twelve numbers: their magic, stats by level and starting equipment, their portraits, sprites and what they say | — | Cast | Data |
| **Monsters** | every monster: its battle sprite, stats, drops, attacks, where it is met | Monsters, Attacks | Cast | Data |
| **Portraits** | the portraits, under whose they are: a character's or no one's | By character, Portrait lists (technical) | Cast | Graphics |
| **Sprites** | by who: Party / Story people / People / Monsters / Things, one entry per look | By who, In battle, Pages (technical), Object sets | Cast | Graphics |
| **Dialogue** | every message, by where it is said | Lines, Window, Markup (technical) | Story | Text |
| **Movies** | the movies, by the game's titles | Play, Frame, Details (technical) | Story | Video |
| **Story flags** | what the game remembers you have done, and what each flag changes | — | Story | Data |
| **Items** | every item; what can be worn; every shop; every chest | Items, Equipment, Shops, Treasure | Adventure | Data |
| **Magic** | every spell, by who learns it | — | Adventure | Data |
| **Battles** | every fight: its monsters, where it starts, its music | Battles, Monster sets (technical) | Adventure | Data |
| **Music** | the soundtrack, by the game's titles, each linked to where it plays | Music, Arrangement (technical) | Sound | Audio |
| **Voices** | every voice line, by speaker, with the message it goes with, and what plays it in battle | — | Sound | Audio |
| **Sound effects** | every sound effect | — | Sound | Audio |
| **Bromides** | the bromides, each with its voice | — | Art | Graphics |
| **Menus** | the menus' art: windows, icons, the font | — | Art | Graphics |
| **Screens** | the full-screen pictures: title, disc change, the end | Screens, All images (technical) | Art | Graphics |
| **Disc** | each disc: its identity, what can be read | — | — | Disc |
| **Disc files** | the disc's file system | — | — | Disc |
| **Resources** | every resource of the game's archive, by number | — | — | Disc |
| **CD tracks** | the disc's audio tracks | — | — | Disc |
| **Sound banks** | the banks, their sequences and samples | Banks, Sequences, Samples, Files | — | Audio |
| **Data tables** | the program's tables as stored, field by field | Records, Fields, Provenance | — | Data |
| **Strings** | the string table; the text the program keeps | String table, In the program | — | Text |

The two rails, in order:

| Fan mode | | Advanced mode | |
|---|---|---|---|
| **World** | Maps | **Disc** | Disc, Disc files, Resources, CD tracks |
| **Cast** | Characters, Monsters, Portraits, Sprites | **Graphics** | Maps, Sprites, Portraits, Bromides, Screens, Menus |
| **Story** | Dialogue, Movies, Story flags | **Audio** | Music, Sound banks, Voices, Sound effects |
| **Adventure** | Items, Magic, Battles | **Video** | Movies |
| **Sound** | Music, Voices, Sound effects | **Text** | Dialogue, Strings |
| **Art** | Bromides, Menus, Screens | **Data** | Data tables, Story flags, Battles, Characters, Monsters, Items, Magic |

## The kinds

For each kind: its name, how one is written, what it is, the code's name
for it (which the extended info shows), and its home — the tab a card's
*Open in* goes to. Everything is the US program's (SLUS_006.28); the
Japanese program numbers things the same.

### The world

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| map | `map 21` | one of the 97 maps | map (`g_MapNumber`, `g_MapResourcePairs`) | Maps |
| place | `place 82` | the place name a map shows; maps are grouped by it | place (`g_MapPlaceName`; string 1024 + its number) | Maps |
| entrance | `entrance 21/5` | one of a map's ways in: the map, object set, sound and spot it changes to | enter row (`g_MapEnterTable`, `MapChange (0x8005922C)`) | the map |
| camera limits | of an entrance | the part of the map the camera keeps to after that way in | map limits (`g_MapLimitLeft` …) | the map, *In game* |
| party move | `party move 21/2` | a move of the party inside its map | party place row (`g_MapPartyPlaceRows`) | the map |
| tile change | `tile change 21/3` | a change of the map's tiles: a door opening, a bridge drawn | bg change (`MapBgChangeStart (0x80059900)`) | the map's Story flags panel |
| cell | `cell 21/(x, y)` | a square of the map's attribute plane, and what stepping on or examining it runs | attribute cell (`MapAttributeRun (0x800590C0)`) | the map |
| tile animation, palette animation | `tile animation 3` | the moving tiles and colours of a map | tile / palette animation set (`g_TileAnimationSets` …) | the map |
| story flag | `story flag 1153` | one thing the game remembers about your progress | story bit (`g_StoryBits`, `StoryBitSet (0x800576EC)`) | Story flags |

### On the maps

A map's entities, triggers, map monsters and chests are **objects**, each
made from a definition of the map's **object set**. The definition is what
stays the same from visit to visit, so it is what a reference points at,
and its number is the one the scripts use to add or remove that object
(commands 0x25, 0x41). A nameless object is titled where, what and its
number: *‹place› · entity 3*.

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| object set | `object set 21` | the definitions, sprites and pages a map is entered with | object set (`g_MapObjectsDataResourceNumbers`) | Sprites, *Object sets* |
| entity | `entity 21/3` | someone or something the party can talk to | object kinds 1–3 (`MapPartyTalkCheck (0x80067D1C)`) | the map |
| trigger | `trigger 21/3` | an object that runs something when the party touches it | object kind 4 (`MapObjectTouchRun (0x8007ACD8)`) | the map |
| map monster | `map monster 21/3` | a monster walking the map; touching it starts a battle | object kinds 5, 6 (`MapObjectTouchRun` → `MapBtlRun`) | the map |
| chest | `chest 21/3` | a chest, or something to examine: an item, money or a scene inside | object kind 7 (`MapObjectKind7Run (0x80067F84)`) | the map; Items, *Treasure* |
| actor | `actor 11/420` | an object a script makes for a scene | actor (`ScriptCommandMoveChrRowActorSet (0x80061EAC)`) | the scene's script |
| behaviour | `behaviour 2` | how an object moves: stands, wanders, follows | think (`MapObjectsThink (0x8006736C)`) | — |

### Characters, monsters and their pictures

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| character | `character 1` | one of the party's numbers, 1–12, with a character record each and the string table's name; the code gives no one else a number | character record (`g_ChrRecords`, `g_PartyIds`); face file | Characters |
| portrait | `portrait 7` | a face shown beside a message, five a file. Character n's are file n's, (n − 1) × 5 + 1 to + 5, and the copies of their pictures in other files; the faces of files 13–24 are no one's, each a speaker of its own; who is drawn there is not said, since naming them would be a judgement by eye | face (`FaceCellSet (0x8001B3DC)`, `FaceListByteLoad (0x80076094)`) | Portraits |
| portrait list | `portrait list 5` | the portraits a scene loads beside the party's | face list (`g_FaceList`, `ScriptCommandFaceListSet (0x8005E610)`) | Portraits, *Portrait lists* |
| sprite | `sprite 21/35` | a walking sprite: its pieces, poses and animations | sprite data (`g_MapSpriteDataEntries`) | Sprites |
| look | — | sprites drawing the same pixels wherever they are copied; the Sprites list shows one entry per look, titled by who wears it | — (the viewer's) | Sprites |
| pose, animation, piece | of a sprite | one picture; a run of poses; one rectangle of a pose | (`sprite_pages`) | the sprite |
| twin | of a sprite | the second sprite drawn beside an object or a party member; a party member's is shown as their shadow (`‹name›'s shadow`) | twin (`g_MapTwinSpriteDataNumbers`) | the sprite |
| battle sprite | `battle sprite 12/3` | a monster's or a character's sprite in battle | enemy block, party block (`BtlDataLoad (0x80018694)`, `BtlPartyLoad (0x8002B114)`) | Sprites, *In battle* |
| palette row | `palette row 506` | a row of colours in video memory a picture is drawn through | CLUT row | the Inspector |

### Story

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| message | `message 11/37` | one message: the 37th of script 11 | message (`MessageDisp`, command 0x02) | Dialogue |
| choice | of a message | a question's two answers | answer (`MessageAnswerRun`, command 0x07) | the message |
| script | `script 11` | the scripts the messages and scenes live in, titled by the places that run them | script (`g_ScriptResourcePairs`) | Dialogue |
| label | `label 11/18` | where a script starts: talking to someone, touching something, stepping on a cell | label (`ScriptLabelRun (0x80059FDC)`) | Dialogue, *Markup* |
| movie | `movie 18` | a movie, titled as the game titles it | movie (`MoviePlay (0x800232D4)`) | Movies |
| bromide | `bromide 3` | a bromide: its picture and its voice | picture (`PictureShow (0x80024A7C)`; movie numbers 55–67) | Bromides |

### Adventure

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| item | `item 18` | an item; one that can be worn is equipment | item (`g_BtlItemTable`) | Items |
| shop | `shop 5` | a shop and its stock, up to six items | shop (`ShopRun (0x80050694)`, `g_ShopStockRows`) | Items, *Shops* |
| money | an amount | money a chest or a scene gives | (`g_MapObjectKind7Amounts`) | — |
| spell | `spell 16` | one spell of the Magic menu | spell (`g_BtlSpellRows`) | Magic |
| battle | `battle 46` | one fight: its monster set and monster group | battle number (`g_BtlNumber`, `g_BtlNumberRows`) | Battles |
| scripted battle | `scripted battle 5` | a fight a scene starts, with its own party | script battle row (`g_ScriptMapBtlRows`) | Battles |
| monster | `monster 5` | one kind of monster | enemy (`g_BtlEnemyRows`) | Monsters |
| monster attack | `monster attack 28` | something a monster does in battle | attack row (`g_BtlAttackRows`) | Monsters, *Attacks* |
| monster set | `monster set 12` | the graphics a battle loads: the arena and its monsters | enemy set (`g_BtlEnemySet`, `g_BtlDataResources`) | Battles, *Monster sets* |
| monster group | `monster group 64` | who stands where in a fight, up to eight | enemy group (`g_BtlEnemyGroups`) | the battle |
| battle effect | `battle effect 35` | how a battle shows an action | show (`BtlShowNumberRun`) | the battle |
| battle slot | of a battle | a place in battle: 0–5 the party, 6–13 the monsters | slot (`g_BtlSlotIds`) | — |

### Sound

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| song | `song 12` | a piece of the soundtrack, titled as the game titles it | music (`MusicPlay (0x80054F2C)`, `g_MusicNumber`) | Music |
| voice | `voice 18` | a voice line | voice (`VoiceSet (0x80055470)`, `g_XaVoices`) | Voices |
| sound effect | `sound effect 13`; a place's own `sound effect 300/131` (ruled 2026-10-26) | a sound effect: numbers 1–24 the same sound everywhere, the battle's from 31; from 131 each place has its own sound for a number, written with the sound bank of that place's set first | sound (`SoundPlay (0x800555F0)`, `g_SoundIds`) | Sound effects |
| sound bank | `sound bank 232` | a bank of samples and the sequences played through it | VAB + SEQ (SOUND.C) | Sound banks |
| sequence | `sequence 232/0` | one score of a bank | SEQ | Sound banks, *Sequences* |
| sample | `sample 232/3` | one sampled instrument or sound of a bank | VAG | Sound banks, *Samples* |
| sound area | `sound area 7` | which bank a map's sound effects come from | sound area (`g_SoundMapAreas`, `g_SoundAreaBankPairs`) | the map |

### Art

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| image | `image 3/1` | a picture kept in a resource: a screen, a page of the font | TIM (`resource_tim_add (0x800208A0)`) | Screens |
| icon, glyph | `icon 18` | a menu icon; a letter of the font | icon, glyph (ICON.C, ANKPRINT.C) | Menus |

### The disc and its storage (Advanced mode)

| kind | written | what it is | the code's name | home |
|---|---|---|---|---|
| game | `game lunar-1` | every disc of one game, opened as one | — (the library's slot) | Library |
| disc | `disc US 1` | one disc | — (gamedb) | Disc |
| disc file | `disc file 3` | a file of the disc's file system, numbered in name order on its disc; its card is titled by its name | ISO 9660 | Disc files |
| resource | `resource 488` | an entry of the game's archive, by the number the game reads it by | resource (`g_ResourceSectorPairs`) | Resources |
| CD track | `CD track 2` | an audio track of the disc | the CUE sheet | CD tracks |
| data table | `data table items` | one of the program's tables, as stored | its register name (`g_BtlItemRows` …) | Data tables |
| string | `string 1350` | an entry of the game's string table | string (`font_string_put (0x80026F78)`) | Strings |
| program text | `program text 4` | text the program keeps: the packing dictionary, short place names for saves, the developers' own | (`formats.script_text`) | Strings, *In the program* |

## The cards

A link opens a thing's **card** over the page, laid out simple to complex:

1. **Who or what it is:** its title (*‹place› · entity 3*, a monster's
   name, a song's title) and its reference in decimal.
2. **Its picture or sound:** a sprite animating, a portrait, a voice
   playing, a message in the game's window, a song on the transport.
3. **Its facts in plain words:** what it says, what it holds, what it
   costs, what it changes.
4. **Its links, grouped by kind:** what it points at and what points at it
   (a sprite lists who wears it; an item lists the chests, shops and
   monsters that give it).
5. **Extended info** (folded in Fan mode, open in Advanced): the code's
   name, the number in hex and as the specification writes it, where it is
   stored (resource, offset), and the function that proves each fact and
   link.

Every card has *Open in ‹its home›*. The Inspector beside a tab is laid
out the same way.

## The links

What the code makes of one thing to another. *Have* is read by a decoder
today; *new* is named in the code or the specification and not read yet.

| from → to | through | proven by | today |
|---|---|---|---|
| map → place, script, song, animations | its map record, bytes 6, 8, 0xF, 4, 5 | `g_MapTbls` | have |
| map → entrances → map, object set, sound effect | the map's entrance rows (byte 3 goes to `SoundPlay (0x800555F0)`) | `MapChange (0x8005922C)` | have |
| map → tile changes → story flags | rows at the map payload +0xA00, byte 4 | `MapBgChangeStart (0x80059900)` | have |
| object set → definitions → sprites | definition byte 1 | `MapObjectInit (0x800656CC)` | have |
| object → the story flag that hides it; chest → the one that opens it | byte 2; the chest's own | `MapObjectsInit (0x800655C8)` | have |
| map monster → the story flag it sets when beaten | byte 2, its own number on the map | `MapObjectTouchRemove (0x8007B5CC)` | have |
| map monster → battle | definition byte 0xB | `MapObjectTouchRun (0x8007ACD8)` | have (battle music) |
| entity → label | definition byte 0xB, run in the map's script | `MapPartyTalkCheck (0x80067D1C)` | have |
| trigger → label | definition byte 0xB | `MapObjectTouchRun` | have |
| chest → item, money or label | byte 0xB: an item, an amount, or a label | `MapObjectKind7Run (0x80067F84)` | have |
| cell → label (signs, counters, shelves) | cell kinds 4, 5, 6 | `MapAttributeRun (0x800590C0)` | have |
| script → the maps that run it | map record byte 8; commands 0x42, 0x5D | `ScriptChange` | have |
| label → messages, in order | the label's commands to its end, through jumps and story-flag checks | the command table | have |
| label → the story flags it sets, clears and checks; a check's flag → the label it goes on at | commands 0x09–0x1A and 0x5C; the flags 0x23/0x24 (party ids), 0x25/0x41 (objects) and 0x2D (movies) touch | `ScriptCommandStoryBitsSet (0x8005C504)` and the rest, `StoryBitSet (0x800576EC)` | have |
| message → portrait → character | 0xFAnn / 0xFBnn; a character's file or a copy of their picture | `MessageFaceSet (0x8005B36C)`, `FaceListByteLoad (0x80076094)` | have |
| message → strings | 0xF0nn–0xF6nn | `MessageControlRun` | have |
| label → voice → the voice's sectors | command 0x52, then `g_XaVoices` | `ScriptCommandVoiceSet (0x8005E9FC)`, `VoiceSet (0x80055470)` | have |
| voice → message | the voice command beside the message command in the script | (where they sit; no table) | have |
| label → scripted battle → battle | command 0x2B | `g_ScriptMapBtlRows` | have |
| label → shop → items | command 0x2E → `g_ShopStockRows` | `ScriptCommandShopRun (0x8005E384)`, `ShopRun (0x80050694)` | have |
| **label → movie, song, sound effect, portrait list, place, items given, party joins, spells, story flags** | commands 0x2D, 0x30, 0x31, 0x3E, 0x49, 0x1F–0x22, 0x23/0x24, 0x59, 0x09–0x1A | each `ScriptCommand…` | have for songs, sound effects and story flags (by the scenes that run them); **new** for the rest |
| label → actors → sprites | command 0x34 | `ScriptCommandMoveChrRowActorSet (0x80061EAC)` | have |
| battle → monster set, monster group → monsters | `g_BtlNumberRows`, `g_BtlEnemyGroups` | `BtlRun (0x80027434)` | have |
| battle → song (what starts it; the win) | its starters; the boss class | `MapBtlRun`, `BtlRun` | have (battle music) |
| monster → name, items dropped, attacks, sounds | its row | `g_BtlEnemyRows` | have |
| item → who can wear it, the story flag while worn, picture | its row | `g_BtlItemTable` | have |
| spell → character | its row | `g_BtlSpellRows` | have |
| character → name, portraits, sprites, record | their number | `g_ChrRecords` | have |
| song → sound bank or CD track, title | `g_MusicBankNumbers`; song 60 | `MusicPlay (0x80054F2C)` | have |
| sound effect → bank, sequence; map → sound area | `g_SoundIds`; `g_SoundMapAreas` | `SoundPlay (0x800555F0)` | have |
| movie → disc file, title, the story flag it sets | its number | `MoviePlay (0x800232D4)` | have |
| bromide → voice | voices 100–103 | `g_PictureVoices` | have |
| spell, monster attack → voice | its show's effect row, bytes 2 and 3 (the other voice for character 11 and monsters 11, 124, 125) | `BtlShowOpen (0x8007B7C8)`, `g_BtlEffectRows` | have |
| battle → voice | battles 245, 246, 247, 254: before the monster in slot 6 acts with a show of its own | `BtlActingShowRun (0x8003A158)` | have |
| character → voice | character 12 bringing a fallen party member back | `BtlSlot5Revive (0x80028E5C)` | have |
| voice → who says it in battle | who casts it: a spell's characters (the spells they keep, by level or command 0x59; the ones they pick acting by themselves), an attack's monsters (their row; their id's planner, in battles 0xEB and up), a set battle's first monster, the reviver | `ChrLevelUp (0x80028554)`, `ScriptCommandChrSpellSet (0x8005EE30)`, `BtlActingSpellPick (0x800393F0)`, `BtlEnemyActionSpecialSet (0x800417E4)` | have |
| string → its kind | the string table's number ranges | the string table | have |
| resource → its kind, its home | the archive's regions | `g_ResourceSectorPairs` | have |

## How a link works

- **One reference type.** The backend writes a thing as `{kind, id}`
  (`viewer_tabs/refs.py`) and the app shows it as a link: its title and
  its kind's icon. A song is a link of kind *song* like any other.
- **One index.** When a game opens, the backend builds the links above
  once and keeps them for the session (`viewer_tabs/links/`).
- **One card,** laid out as above, with *Open in ‹its home›*.
- **Back and forward.** Following links is a history, as in a browser
  (Alt+← / Alt+→), so no link strands you.
- **The scene you watch** (ruled 2026-10-26). A script's command is
  credited to every label whose run can reach it: from the label's start,
  through its jumps and calls, every way its tests go, and on into the
  script a 0x42 hands over to (`ScriptCommandScriptChange (0x8005BFCC)`:
  the scene goes on there; the debug room's hand-overs are not followed). A
  song, a sound effect and a story flag are credited alike, so a scene that
  calls a shared label sets the flags the shared label sets (*Set by*,
  *Cleared by*, *Checked by*). A label reads as the scene a player meets
  where the code shows what starts it: talking to someone or touching
  something in a script that can run on their map, stepping on or
  examining a square of the map; a label nothing starts itself reads as
  part of the scenes whose run reaches it (*part of talking to ‹who›*)
  (`viewer_tabs/links/scenes.py`).
- **Scenes, not pieces** (ruled 2026-10-26). What a song, a sound effect
  or a flag lists are the scenes a player sees: the labels something
  starts, and a label nothing found starts that is part of no scene, as
  itself. A piece of a scene is folded into it; the scene already reaches
  all the piece does. The pieces whose code holds the command are *Held
  in*, and a check's *Goes on at* is where the check jumps: the code's
  workings, shown with the extended info in Fan mode and open in Advanced
  (`links.advanced_groups`). A piece's own card still links what its code
  does, and the Story flags list places and words a flag by its scenes.
- **Each scene once** (ruled 2026-10-26). A scene is listed once however
  many of its pieces reach the command, and a scene whose script runs on
  several places once, under all of them together (*Scenes at ‹A› and
  ‹B›*); past three places the heading names three and says how many more,
  and the scene's note names them all.
- **Found by reference, not by position.** A tab answers where a reference
  lives in it, its view and entry (`GameSession.locate`), whatever the
  list's order.
- **Two rails, one set of tabs.** Each mode's rail is a list of groups of
  tab keys; a tab says which of its views is the technical one. Changing
  mode changes nothing else: the open tab, the card and the history stay.
- **One key per tab.** The app keys a tab by a short stable key (`maps`,
  `portraits`), not its class name or its place in the rail, and each
  provider's class is named for its tab (`MapsProvider`,
  `PortraitsProvider`).

## Words retired

| word | meant | now |
|---|---|---|
| event | a script; a story flag; a movie; definition byte 0xB; a cell | script; story flag; movie; label / battle / contents; cell |
| scene (as a name) | an entrance; a portrait list; the battle's function table; a movie | entrance; portrait list; (code only); movie |
| area | the map record; a place; a sound area; the camera's limits | map record; place; sound area; camera limits |
| encounter | a battle | battle |
| formation | a monster group (the game's menus use the word for the party's order) | monster group |
| enemy, template | a monster | monster |
| location | a place | place |
| set, row, record, kind, page, frame, layer (alone) | a dozen things | always qualified: *object set*, *palette row*, *object kind* … |
| track (alone) | a CD track; the transport's clip; an actor's motion | CD track; clip; motion |
| EXE | the program | program (*In the program*); *SLUS_006.28* in extended info |
| picture (alone) | a TIM; a face; a bromide | image; portrait; bromide |
