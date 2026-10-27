"""The desktop app's backend: the viewer's tab providers, served over HTTP.

`app/` is a Tauri window drawing a React UI. Everything it shows is
produced HERE, by the `viewer_tabs.tab_providers` classes, so no decoder is
re-derived on the web side. The decoders themselves are in `decoders`.

    server.py     entry point: binds 127.0.0.1, prints one READY line
    routes.py     the HTTP API: routing, the token check, Range requests
    library.py    the extracted discs (<library>/<program>/raw/<disc>/) + import
    index.py      each disc's index, kept in the library, and its indexer
    session.py    one opened game: its discs' DiscContexts and fresh providers
    merge.py      one tab's items from several discs, as one list
    present.py    SelectResult -> the JSON the UI renders
    video.py      STR movies, decoded in chunks the UI pulls and schedules
    music.py      a score played live, in chunks the UI pulls
    blobs.py      rendered images and audio clips, fetched by URL
    jobs.py       long-running work (extraction) + progress
    exporting.py  user-initiated output into <library>/<program>/exports/
"""
