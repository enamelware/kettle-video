# Sample library

A small library of Blender open movies, used instead of anyone's own films for running the app, examples and public screenshots. It lives outside the repo, at `~/Videos/kettle-sample-library` on the Steam Deck; no media is ever committed. Automated test files keep invented names (see `CLAUDE.md`).

Every film is by the Blender Foundation / Blender Studio, under a Creative Commons Attribution licence. Any screenshot that shows this content carries the credit line:

> (CC) Blender Foundation | studio.blender.org

The library folder has its own `CREDITS.md` with the same information.

## What's in it (3.57 GB)

```
kettle-sample-library/
├── CREDITS.md
├── Movies/
│   ├── Big Buck Bunny (2008)/
│   │   ├── Big.Buck.Bunny.2008.1080p.BluRay.x264-KETTLE.part1.mov
│   │   ├── Big.Buck.Bunny.2008.1080p.BluRay.x264-KETTLE.part2.mov
│   │   └── poster.jpg
│   ├── Elephants Dream (2006)/
│   │   ├── ._Elephants Dream (2006).mov        (empty macOS leftover)
│   │   ├── Elephants Dream (2006).mov
│   │   └── poster.jpg
│   ├── Sintel (2010)/
│   │   ├── Sample/Sintel.2010.1080p.BluRay.x264-KETTLE-sample.mkv
│   │   ├── Sintel.2010.1080p.BluRay.x264-KETTLE.mkv
│   │   ├── Sintel.2010.1080p.BluRay.x264-KETTLE.<language>.srt   (41 files)
│   │   └── poster.jpg
│   ├── Tears of Steel (2012)/
│   │   ├── Tears of Steel (2012).webm
│   │   ├── Tears of Steel (2012).<language>.srt                  (24 files)
│   │   └── poster.jpg
│   └── Test Clips/
│       ├── Sintel (2010) - Test Clip - 1080p HEVC.mkv
│       └── Tears.of.Steel.2012.TEST.CLIP.2160p.UHD.HEVC.10bit-KETTLE.mkv
└── TV Shows/
    └── Caminandes/
        ├── poster.jpg
        └── Season 01/Caminandes - S01E02 - Gran Dillama.mp4
```

The cases it covers: clean names and dotted release names (the tag KETTLE is invented, never a real release group), a film in two numbered parts, a `Sample` folder, an empty `._` file, subtitles beside their films, pictures beside the videos, a TV show with a missing episode 1, five different formats (H.264 in MOV, MKV and MP4, VP8 in WebM, HEVC in MKV), and two heavy HEVC clips. Today's parser joins the two parts, skips the Sample folder and the `._` file, and lists each test clip as a second copy of its film (same title and year).

## Films and licences

| Film | Licence | Official source |
|---|---|---|
| Elephants Dream (2006) | CC BY 2.5 | download.blender.org/ED/ (1024 wide, the largest offered) |
| Big Buck Bunny (2008) | CC BY 3.0 | download.blender.org/peach/bigbuckbunny_movies/ |
| Sintel (2010) | CC BY 3.0 | download.blender.org/durian/movies/ |
| Tears of Steel (2012) | CC BY 3.0 | media.xiph.org/tearsofsteel/ |
| Caminandes 2: Gran Dillama (2013) | CC BY 4.0 | download.blender.org/demo/movies/ |

Licences checked on 2026-11-17 on each film's official pages. The subtitles (Sintel: download.blender.org/durian/subs/, Tears of Steel: media.xiph.org/tearsofsteel/subtitles/) are volunteer translations published beside the films with no licence of their own stated, so they are used locally only and never published.

## What was changed

- **Renamed:** every file, to the layout above.
- **Split:** Big Buck Bunny into two parts at about 5:01, without re-encoding.
- **Cut:** Sintel's `Sample` is a 34-second excerpt from 2:00, without re-encoding.
- **Re-encoded:** the two test clips, each 3 minutes. Tears of Steel from 1:00, upscaled from 1920×800 to 3840×1600 as 10-bit HEVC (not the 4K original, which wouldn't fit the 10 GB budget); Sintel from 2:00 as 1080p HEVC. Both keep the original sound.
- **Added:** the empty `._` file, and the `poster.jpg` pictures, each a single frame grabbed from the film. No official posters, title cards or logos: logos are not covered by the licence.

## Tears of Steel and promotion

Tears of Steel's live-action footage shows real actors and can't be used commercially, so its frames stay out of anything promotional (store pages, banners, release images). Development and test screenshots are fine, with the credit line. Its separately published soundtrack album is CC BY-ND and is not part of the library; the film's own sound is part of the CC BY film.

## Not included yet

On studio.blender.org the newer films download only with a login (most need a subscription), so these were left out: Sprite Fright, Spring, Charge, Agent 327: Operation Barbershop, Hero, Coffee Run, Wing It!, Cosmos Laundromat, and Caminandes 1: Llama Drama and 3: Llamigos. They can be added later from the designer's own download, with this page and `CREDITS.md` updated.

## Using it on this device

`settings.json` on the Deck points at the library's `Movies` and `TV Shows` folders; the previous paths are kept in `data/settings.before-sample-library.json` (git ignores `data/`). The app loads its saved library at launch, so rescan once after switching.

The privacy guard's `build` step takes film and show names from the cards only, never from the home folder, so the sample library's titles never become private words (a test keeps it that way, the sample library guard fix). Keep the library in the home folder: on a card, its titles would be added to the list and this page would fail the guard.
