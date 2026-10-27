# The user guide

Everything the Eternal Silver Asset Viewer shows, and where to find it.
The [README](../README.md) gets you started in a few minutes; this page
goes through each screen in turn.

- [Disc images](#disc-images)
- [The Library](#the-library)
- [Opening a game](#opening-a-game)
- [Finding your way around](#finding-your-way-around)
- [Fan mode and Advanced mode](#fan-mode-and-advanced-mode)
- [The tabs](#the-tabs)
- [Listening](#listening)
- [Saving pictures and sounds](#saving-pictures-and-sounds)
- [Keys and mouse](#keys-and-mouse)
- [The library folder](#the-library-folder)
- [When something goes wrong](#when-something-goes-wrong)

## Disc images

The viewer reads disc images: copies of your discs as files. Make one of
each disc with a disc-imaging program, as a **`.cue` file with its `.bin`
file or files**: a raw copy of every track. That copy holds everything the
games use: the data, the CD audio tracks, the voices and the movies'
sound.

The viewer also opens an **`.iso`**, or a **`.bin`** on its own, but they
hold less. An `.iso` keeps only part of each sector, so the voices and the
movies' sound cannot be read from it, and it has no CD audio. A `.bin`
without its `.cue` has the data but not the list of tracks, so its CD audio
is not found.

The viewer knows the checksum of a good copy of each disc it reads. A disc
whose image matches is marked with a green check in the Library; one that
does not match is still read, and marked "identified by SYSTEM.CNF only"
(see [When something goes wrong](#when-something-goes-wrong)).

It reads these discs:

| Game | Disc | Serial |
|---|---|---|
| *Lunar: Silver Star Story Complete* (US) | disc 1, disc 2 | SLUS_006.28, SLUS_008.99 |
| | *The Making of* (bonus disc) | SLUS_009.21 |
| | the demo | SLUS_900.55 |
| *Lunar: Silver Star Story* (Japan) | disc 1, disc 2 | SLPS_013.97, SLPS_013.98 |
| *Lunar 2: Eternal Blue Complete* (US) | discs 1, 2, 3 | SLUS_010.71, SLUS_012.39, SLUS_012.40 |
| | *The Making of* (bonus disc) | SLUS_012.57 |
| | the demo | SLUS_900.83 |

Discs of other games are not added. Lunar 2 is **not fully supported yet**:
it shows only what any PlayStation disc has: its movies, and in Advanced
mode the disc and its files. Its maps, characters, story and music cannot
be read yet.

Keep your images where they are once added. The viewer copies each disc's
files into its library, but plays the CD audio, the voices and the movies'
sound straight from the image, and extracts a disc again from it.

## The Library

The Library is the first screen, and the top button of the bar on the left
comes back to it. It holds a **card for each game**, Lunar and Lunar 2,
and each card lists every disc of every version of that game.

At the top:

- **Add a folder…** looks through a folder and its subfolders for disc
  images, and extracts every one the library does not hold yet, one after
  another. When it is done it lists what it skipped, and why: already in the
  library; another copy of a disc it has just added; a disc the viewer does
  not know; not a game disc; or an image it could not read. One bad image
  does not stop the rest.
- The **circular arrow** looks again, after you change something on disk.
- The **folder button** switches to another library folder (see
  [The library folder](#the-library-folder)).

The bar on the left shows icons only: hold the pointer over one to see its
name.

On a game's card:

- **Open** opens the game with every disc of it you have added.
- **Re-extract all** extracts every disc of it again from its image,
  replacing what was there. It asks first, and skips a disc whose image
  has moved.

On each disc of a card, one of:

- **A green check**: added, and its image matches a known good copy.
- **A yellow note**, "identified by SYSTEM.CNF only": added, but its image
  does not match a known good copy.
- **"disc image not found"**: added, but its image is no longer where it
  was. The disc opens, without its CD audio, voices and movie sound.
- **"waiting to be indexed · opens meanwhile"**: just added. The viewer
  reads it through once in the background, so that it opens quickly later;
  until then it opens all the same, a little slower.
- **Add…**: not added yet. Choose its `.cue` (or `.iso` or `.bin`) and it
  is extracted.

A disc already added has a **re-extract** button of its own, shown when
the pointer is over the disc. It asks first; if the disc's image has
moved, it asks where it is now.

Images you put in the library's `discs` folder that the viewer has not
identified yet are listed under the cards, each with an **Add** button:
added, a disc joins the game it belongs to.

## Opening a game

**Open** on a card opens that game with all its added discs at once. Every
tab lists what all the discs hold, each entry tagged with the discs it is
on: **US 1**, **US 2**, **JP 1**, **Making-of** and so on. Something that is
the same on several discs is listed once. Something that differs between
discs, such as a movie in its Japanese and English cuts, is listed once
with a switch between its **versions**.

The open game's header strip names it, with a badge for each of its
discs, and a "not fully supported yet" badge when it is not read in
full. Its **X** closes the game. The Library button leaves the game open,
to come back to.

## Finding your way around

With a game open, the window has five parts:

- **The bar on the left**: the Library button, then the game's tabs in
  groups, as icons; hold the pointer over one to see its name. Under them
  are the **ADV** switch (see
  [Fan mode and Advanced mode](#fan-mode-and-advanced-mode)) and the
  keyboard button, the list of keys.
- **The list**: what the tab holds. Some tabs have more than one view,
  chosen above the list; Items, for example, has Items, Equipment, Shops
  and Treasure. Type **/** to filter the list.
- **The stage**, in the middle: what you picked, drawn, playing or written
  out. Its toolbar zooms, shows the grid and saves (the download button).
- **The Inspector**, on the right: the facts about what you picked, and its
  links. **I** hides and shows it. **Open card** opens its card.
- **The player bar**, along the top: whatever is playing (see
  [Listening](#listening)). It stays there on the Library too.

### Links and cards

Things link to the things they touch: a monster to the battles it is in,
an item to the chests, shops and monsters that give it, a song to the
places, battles and scenes that play it, a person on a map to what they
say. Click a link and its **card** opens over the page: what it is, its
picture or sound, its facts, and its own links. **Open in …** goes to its
tab.

Following links is a history, as in a web browser: a card's **Back** and
**Forward** buttons, **Alt+←** and **Alt+→** (**⌥←** and **⌥→** on a
Mac), or the mouse's back and forward buttons. **Esc** closes the card.

## Fan mode and Advanced mode

The viewer opens in **Fan mode**: the game as a player knows it, in the
groups a fan wiki uses. The bar's **ADV** switch, under the tabs, turns on
**Advanced mode**: how the game is made, every tab grouped by the kind of
file it reads. The viewer remembers which you chose.

| | Fan mode | Advanced mode |
|---|---|---|
| the bar | World, Cast, Story, Adventure, Sound, Art: 17 tabs | Disc, Graphics, Audio, Video, Text, Data: all 24 tabs |
| a tab opens on | its first view | its technical view, where it has one |
| a card's extended info | folded | open |

Advanced mode has seven tabs more; the tabs both have, and the cards and
links, are the same in both, and switching keeps your place. Following a
link to a tab only Advanced mode has turns Advanced mode on.

A card's **extended info** (folded in Fan mode, a click opens it) gives the
technical side of a thing: the name the game's code gives it, its number in
hex, where it is stored, and the function in the game's program that proves
each fact.

Every thing has one reference, such as `map 21` or `battle 46`: in its
list, on its card, in links to it and in the names of its exported files.
Advanced mode gives the number in hex too. [Names](taxonomy.md)
lists them all.

## The tabs

In Fan mode's order, then the tabs only Advanced mode shows.

### World

**Maps.** Every place the party walks: the overworld, the towns and the
dungeons, each drawn as the game draws it, with the people, monsters and
chests that stand there moving as they do in the game. Click someone or
something to see who or what it is, and play the place's music with its
**♪** button. **In game** shows what a player sees; **Raw** shows the
whole map, the parts the game never shows included. The toolbar turns the
map's layers on and off, plays its animations at the game's speed or a tick
at a time, and opens its tileset. **Objects** lists everyone and everything
the map places, and **Story flags** the flags that change the map, its
doors and its other tiles, to see it before and after.

### Cast

**Characters.** The game's characters: their portraits; for each the game
keeps stats for, their stats at every level, the magic they learn and what
they start out wearing; and the scenes their portraits come up in.

**Monsters.** Every monster: how it looks in battle, its stats in the
menu's words, what it drops, its attacks and where it is met. **Attacks**
lists every monster attack. The debug room's battles come last.

**Portraits.** Every portrait the game shows beside what people say, under
whose it is: each character's, then the ones that are no character's, then
the blank ones.

**Sprites.** Every sprite, by who wears it: the party, the story's people,
the other people, the monsters and the things on the maps, each playing its
animations. **In battle** shows everyone as they look in battle.

### Story

**Dialogue.** Everything said in the game, scene by scene: each line with
who says it, and the questions the game asks. **Window** shows each message
as the game draws its window.

**Movies.** The game's animated scenes, with their sound, playing as they
do in the game. **Frame** holds one picture still, to look at closely or
save. A bonus disc's and a demo's movies are here too, tagged with their
disc.

**Story flags.** What the game remembers you have done: every story flag,
under the place that sets it. A flag's page says what sets it, what clears
it, what checks it and what it changes: a chest shown open, someone no
longer there, a tile changed on the map.

### Adventure

**Items.** Every item; what can be worn, by where it is worn; every shop,
by the place it is in, with what it sells; and every chest that holds
something, by the place it stands in. (A chest that starts a scene is on
the Maps tab.)

**Magic.** Every spell, under the character who learns it, with its menu
icon.

**Battles.** Every battle in the game: the monsters you fight, standing in
their arena as the game puts them, and the party where it stands when a
scene starts the fight with a party of its own. Click one to watch its
animations, and play the music the fight starts with and the jingle of the
win. Each battle says where it is met.

### Sound

**Music.** The soundtrack, by the game's own titles, in the jukebox's
order, and where each song plays: the places whose maps play it, the
battles that start or end with it, and the scenes that play it. A song
plays as the game plays it, its loop repeating while the player bar's loop
switch is on.

**Voices.** Every spoken line in the game, under who says it: the words on
screen while it plays, and where it plays: in a scene, with a bromide, or in
battle as a spell or an attack is cast.

**Sound effects.** Every sound effect, and where the game plays it: going
through an entrance, as a tile changes, in a scene, in battle, in the
menus. The common sounds are the same everywhere; from a certain number on,
each place has sounds of its own, so one number can sound different from
place to place.

### Art

**Bromides.** The pictures the game shows whole, each with a spoken line,
when one of the bromide items is used from the menu. Each plays as the game
shows it, looking down the picture and back up.

**Menus.** The menus' own graphics: the letters they print with, the icons
for items, spells and commands, the title screen's pictures, and the
cursors and marks of the menus, the shops and the battles.

**Screens.** The game's full-screen pictures: what it shows before the
title, the title screen, the screens that ask for the other disc and the
two after the game's end. **All images** lists every picture the game
keeps.

### Only in Advanced mode

**Disc.** Each disc: what it is (title, serial, region, its checksum) and
what the viewer can read on it.

**Disc files.** The disc's own files, as a computer would list them.

**Resources.** Every entry of the game's archive, by the number the game
reads it by, and what each holds.

**CD tracks.** The disc's audio tracks, to play.

**Sound banks.** The game's sound banks: each bank's sequences (the
scores) and samples (the instruments and sounds).

**Data tables.** The tables in the game's program, as stored, field by
field: the rows the Items, Magic, Monsters and Characters tabs are read
from, with where each is stored.

**Strings.** The game's string table, and the text the program itself
keeps.

## Listening

Songs, voices, sound effects and CD tracks play on the **player bar**
along the top of the window. Picking one loads it; **Enter** or a
double-click loads and plays it. It plays on while you look at other tabs;
picking another sound while one plays asks first. A map's or a battle's
**♪** button plays its music.

The bar has back to start, stop, play and pause (**Space**), a seek bar,
and for a song the **loop** switch: on, the song's loop repeats as in the
game; off, it plays to its end.

Movies play on the stage, with their own controls; **Space** plays and
pauses the movie on stage.

## Saving pictures and sounds

- **A picture**: the download button in the stage's toolbar saves it as a
  PNG. A sprite or a battle is saved as it stands at its start. A message
  window that animates saves every frame, and a strip of them all.
- **A map**: **Export** in its toolbar offers the map as shown (with the
  layers, story flags and moment on screen), each camera area on its own
  (a town, each house), its layers apart over transparency, or its
  tileset, at 1×, 2× or 4×.
- **A song, a voice or a sound**: **Export** on the player bar saves a
  WAV. For a song you choose how many times its loop plays (1 to 20) before
  its ending. A song can also be saved as a MIDI file: its notes and tempo,
  no sound.

Everything goes in an `exports` folder in the library, the one of the
disc it came from; the Inspector says where. The message after an export
has a **Show in folder** button.

## Keys and mouse

The keyboard button on the bar, or **?**, shows most of this list in the
app.

| key | does |
|---|---|
| ↑ ↓ or j k | previous / next entry |
| Enter or double-click | select and play |
| Space | play / pause (the movie on stage, else the player bar) |
| / | filter the list |
| Ctrl+F (⌘F on a Mac) | find in the text shown, else filter the list |
| [ ] | previous / next tab |
| + − or the wheel | zoom in / out, around the pointer |
| 0 · 1 | fit · actual size |
| G | the 16-pixel grid on and off |
| I | hide or show the Inspector |
| drag | move a picture around |
| Alt+← Alt+→ (⌥← ⌥→ on a Mac), the mouse's back and forward buttons | back / forward through the links followed |
| Esc | close a card |

## The library folder

Everything the viewer writes goes in one folder, its library: the files of
each disc you add, what it keeps of its reading of each disc, and what you
export. By default it is:

- Windows: `%LOCALAPPDATA%\eternal-silver-asset-viewer\library`
- macOS: `~/Library/Application Support/eternal-silver-asset-viewer/library`
- Linux: `~/.local/share/eternal-silver-asset-viewer/library`

Each disc takes about as much room as its image. The Library's folder
button chooses another folder (one with room), or goes back to the default
one. Disc images can be kept in the library too, in its `discs` folder;
they are then listed on the Library, ready to extract.

## When something goes wrong

**macOS or Windows will not open the app.** The app is not signed, so the
system warns the first time. On macOS: **System Settings → Privacy &
Security**, then **Open Anyway** under the message about the app. On
Windows: **More info → Run anyway**.

**Starting is slow.** Each start unpacks the part of the app that reads
the discs, and the first start on a computer can take a minute or more
while the system checks it. If it takes too long, the app says "The
backend did not start": choose **Try again**.

**"The backend did not start".** The part of the app that reads the discs
did not start. The screen shows what it printed; **Try again** starts it
again, and **Choose folder…** tries another library folder, in case the
library's own folder is the trouble.

**A disc was skipped: "a disc the viewer does not know".** The disc is not
one of the discs [above](#disc-images).

**"identified by SYSTEM.CNF only".** The disc's image does not match a
known good copy. The viewer knows the disc by its label and reads it all
the same. An image made another way (an `.iso`, say) gives this, and so
does a damaged one; if something in it looks wrong, make the image again.

**"disc image not found".** The image was moved or deleted after the disc
was added. Put it back where it was; or use the disc's re-extract button,
which asks where the image is now; or put the image, under the same file
name, in the library's `discs` folder, where it is found by itself.

**A disc's image is damaged.** An image too damaged to read is not
added, and the viewer says why. Make the image again.

**The Japanese text shows boxes.** The viewer does not read the console's
own kanji; it draws the Japanese discs' text with a Japanese font from your
computer, and these are the ones it looks for:

- Windows: MS Gothic, Yu Gothic, Meiryo or MS Mincho. Adding Japanese in
  Windows' language settings installs them.
- macOS: Hiragino or Osaka, which macOS comes with.
- Linux: any Japanese font, such as Noto Sans CJK JP.

Install one, then restart the app: it looks for the font once.

**The Japanese discs' shops and chests.** The shops' stock and the chests'
money are not found on the Japanese discs yet; their pages say so.

**On Linux, the terminal shows graphics warnings** such as `MESA-EGL:
warning: … failed to create dri2 screen`. They are harmless: the window's
graphics library trying more than one graphics driver. They show on some
graphics cards, NVIDIA's among them, and only when the app is started from
a terminal.
