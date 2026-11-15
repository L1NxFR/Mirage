# Optimistic web fonts

Downloaded 2026-11-14, byte-for-byte, from `https://conf.reactjs.org/fonts/`.
The filenames and source are documented in React's official downloader:
https://github.com/reactjs/react.dev/blob/main/scripts/downloadFonts.mjs
(source blob: 6a480c750d6ab578b28ecd56e6933f800318e309).
CSS weight/style mappings follow the font OS/2 tables and React's stylesheet:
https://github.com/reactjs/react.dev/blob/main/src/styles/index.css

Included Latin faces:

- Display: 200, 300, 500, 600, 700, 800 normal; 500, 600, 700 italic.
- Text: 400, 500, 700, 800 normal and italic.

Display has no 400 Regular face in this source. Blog headings use Display 700;
Chinese-article Latin prose uses Text 400, with real Text bold/italic faces.
English-article prose uses the existing Latin Modern Roman faces for long-form
reading, selected by the page's HTML language. These are complementary
optical cuts, not identical outlines. Chinese uses the separately bundled
Noto Sans SC Regular/Bold. Code and mathematics retain their specialist fonts.

Optimistic is a Meta font. These files do not include an open-source font
license; the repository's code license and Noto's OFL do not grant rights to
Optimistic. The download source is provenance, not a redistribution license.
This directory must not be labelled MIT/OFL.

The legacy `paper/optimistic-bold-subset.ttf` is a PDF subset with 77 glyphs
and no Unicode cmap. It remains for the existing non-Blog document style;
Blog no longer references it.
