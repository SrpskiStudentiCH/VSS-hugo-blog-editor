# VSS Blog Editor — administratorski alat za Hugo sajt

Administratorska web aplikacija (React + Flask) koja preko GitHub tokena menja
sadržaj **drugog** repozitorijuma — Hugo sajta „Srpski studenti u Švajcarskoj"
(`proton-org-rs/vss-hugo`, grana `main`, deploy na GitHub Pages preko GitHub
Actions na svaki push).

> Detaljna analiza ciljnog repozitorijuma: `ADMIN-ANALIZA.md`.
> Implementacioni zahtevi: `ADMIN-PROMPT.md`.

## Arhitektura

```
backend/
  app.py              # Flask rute (legacy /login, /save + novi /api/*)
  github_client.py    # GitHub REST klijent (tree/contents/Git Data/commits/actions)
  markdown_parser.py  # split/merge front mattera (+++ TOML), round-trip čuva nepoznata polja
  validators.py       # šeme, datumi, imena fajlova, allow-lista putanja, binarna validacija
  hugo_config.py      # string-level izmena samo [params]/[params.contact] u hugo.toml
  yaml_i18n.py        # izmena i18n YAML po ključu, čuva komentare i redosled
  translation.py      # pluggable prevod (openai | gemini | mock | none)
  diff_utils.py       # line diff + commit poruke
  pending_store.py    # in-memory "pending changes" sloj
  repo_service.py     # čitanja (aktivnosti/media/odbor/dokumenta/stranice/postavke) + atomic commit
  tests/              # 59 unittest testova (run: python -m unittest discover -s tests)
frontend/
  src/
    api.js            # API klijent + token sesije
    App.jsx           # shell: login + sidebar + view router
    views/            # Dashboard, Activities, ActivityEditor, Media, Board,
                      # Documents, Pages, Settings, PendingChanges, History
    components/       # Login, Shared (diff, picker, confirm), MarkdownEditor, Preview
    admin.css         # stilovi admin interfejsa
```

## Pravila rada

- **Sve izmene idu u pending sloj** — korisnik akumulira izmene, vidi agregirani
  diff i listu operacija (create/update/delete), pa potvrđuje commit.
- **Atomski commit**: Git Data API (blobs → tree na osnovu HEAD → commit → `PATCH
  /git/refs/heads/main`). Pre commita se ponovo čita HEAD; ako se grana promenila,
  dobija se upozorenje o konfliktu (409) i korisnik osvežava podatke.
- **Validacija**: TOML front matter mora da se parsira (blokira commit); obavezna
  polja po tipu; `YYYY-MM-DD`, `end_date >= date`, `draft` boolean; ime fajla
  `YYYY-MM-DD-slug.md` (events) / slug (blog); allow-lista putanja
  (`content/`, `i18n/`, `static/images/`, `static/documents/`, `hugo.toml` samo
  dozvoljeni ključevi) — sve ostalo je read-only.
- **Brisanje**: soft-delete (draft=true, podrazumevano) pa trajno brisanje uz
  dvostruku potvrdu; `static/images/brand/logo-vss-uss.png` je zaštićen; slike
  koje su referencirane ne mogu da se obrišu (prikazuje se lista referenci).
- **Prevod** prevodi samo: title, description, semester, Markdown telo. Ne dira:
  ime fajla, date, end_date, event_type, image, categories, tags, draft.
- **Legacy tok** `POST /save` (jedan fajl + PNG slika) je **očuvan** —
  refaktorisan na zajednički GitHub klijent, ponašanje nepromenjeno (uz
  obaveznu admin sesiju i validaciju slug-a — vidi „Bezbednost“).

## Env (backend `.env`)

```
GITHUB_TOKEN=...          # scope: contents read+write (samo server, nikad frontend)
REPO_OWNER=proton-org-rs
REPO_NAME=vss-hugo
BRANCH=main
ADMIN_USER=...
ADMIN_PASS=...
FOLDER_PATH=content/posts # legacy /save
PORT=5000
# Opciono — deployment:
# ALLOWED_ORIGINS=https://admin.example.com   # CORS origin-i (default:
#                                             # http://localhost:3000)
# SESSION_TTL_HOURS=12                       # trajanje admin sesije
# Opciono — automatski prevod (besplatno, BEZ API ključa):
# TRANSLATION_PROVIDER=google   (podrazumevano: Google besplatni endpoint,
#                                automatski fallback na MyMemory ako Google
#                                vrati 429/500)
# TRANSLATION_PROVIDER=mymemory | mock | none
# (opciono, AI provajderi — zahtevaju ključ: openai | gemini)
# TRANSLATION_API_KEY=...
# TRANSLATION_MODEL=...
# TRANSLATION_API_URL=...   # za OpenAI-kompatibilne endpoint-e
```

Frontend: `REACT_APP_API_URL` (npr. `http://localhost:5000`).

## Bezbednost (deployment)

- `ADMIN_USER` + `ADMIN_PASS` su **obavezni**: ako nisu postavljeni, ceo API
  vraća 401 (fail-closed), a `/login` vraća 503. `/login` dozvoljava 5 neuspelih
  pokušaja u 5 minuta po IP adresi (429 posle toga).
- Svi mutirajući endpoint-i (uključujući legacy `POST /save`) traže sesijski
  token u `X-Admin-Token` header-u; token važi `SESSION_TTL_HOURS` (default 12h).
- CORS je ograničen na `ALLOWED_ORIGINS` (default `http://localhost:3000`).
- `GET /api/image` servira samo `static/images/**` i `static/documents/**` sa
  dozvoljenim ekstenzijama (JPG/PNG/WEBP/GIF/PDF), uz `X-Content-Type-Options:
  nosniff`; ostali API odgovori nose i CSP/zashita zaglavlja.
- Markdown preview u editoru se sanitizuje (`marked` + `DOMPurify`) jer sadržaj
  dolazi iz repozitorijuma; XSS payload-i (script, onerror, javascript: linkovi)
  se uklanjaju.
- `.env` nikad ne ide u git; `GITHUB_TOKEN` i `TRANSLATION_API_KEY` ostaju samo
  na serveru (greške prevodioca maskiraju ključ).
- Sesije i pending izmene se drže u memoriji procesa — drži **jedan** gunicorn
  worker (`--workers 1`, kako je u `render.yaml`/`Procfile`); uz više workera
  sesije se gube između zahteva.

## Pokretanje

```bash
# backend
cd backend && pip install -r requirements.txt && python app.py

# frontend
cd frontend && npm install && npm start
```

## Deployment (Render)

Repo sadrži `render.yaml` (blueprint) sa ispravnim podešavanjima. Ako servis
pravite/popravljate ručno u dashboard-u, postavite:

| Polje | Vrednost |
|---|---|
| Runtime | **Python 3** |
| Root Directory | `backend` |
| Build Command | `pip install -r requirements.txt` |
| Start Command | `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` |
| Health Check Path | `/api/health` |
| Python verzija | `.python-version` u repou (`3.12`); alternativa: env `PYTHON_VERSION=3.12.5` |

Ako je Root Directory repo root (a ne `backend`), Start Command je
`gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 1 --timeout 120` — root
`wsgi.py` dodaje `backend/` na `sys.path`.

Env promenljive (`GITHUB_TOKEN`, `REPO_OWNER`, `REPO_NAME`, `BRANCH`,
`ADMIN_USER`, `ADMIN_PASS`, opciono `ALLOWED_ORIGINS`) unose se u dashboard;
`backend/.env` se u produkciji ne koristi.

React admin UI se servira iz istog Flask procesa (`frontend/build`), pa je
build **commit-ovan** — posle svake izmene frontenda pokreni
`cd frontend && npm run build` i commit-uj `frontend/build` (source mape se ne
commituju). Bez build-a Flask vraća samo status stranicu „Frontend nije
pronađen“.

**Zašto je deploy pao sa `ModuleNotFoundError: No module named
'your_application'`?** Render tada pokreće svoju *default* start komandu
(`gunicorn your_application.wsgi`) jer Start Command nije podešen. `Procfile`
je Heroku-only i Render ga ne čita, pa Start Command mora da postoji u
`render.yaml` ili u dashboard-u. Posle deploy-a proveri `GET /api/health`
(očekivano `{"status": "ok"}`) i otvori `/` (mora da se učita admin UI).

## Testovi

```bash
cd backend && python -m unittest discover -s tests -v
```

Pokrivaju: markdown split/merge, TOML round-trip (nepoznata polja), validatore,
slug generator, allow-listu, binarnu validaciju, i18n ključeve, hugo.toml
string-level editor, line diff, commit poruke, pending store i atomic commit
builder (blob/tree/commit/ref) sa konflikt-detekcijom.

## Checklist očekivanog ponašanja po funkcionalnostima

### 1. Čitanje repozitorijuma
- [x] Rekurzivni Git Trees listing sa kešom (TTL 5 min); path + SHA + tip po fajlu
- [x] Parser razdvaja `+++` TOML front matter i telo; round-trip čuva nepoznata polja
- [x] Greške API-ja mapirane: 401 token, 403 rate-limit, 404, 409 konflikt

### 2. Pregled aktivnosti
- [x] Grupisanje sr/en/de po entitetu (isto ime fajla); upozorenje ako jezik nedostaje
- [x] Prikaz: naslov, datum, tip, semestar, draft, prisutni jezici
- [x] Filteri: tekst, sekcija, tip, semestar, status, jezik

### 3. Kreiranje aktivnosti
- [x] Forma + dropdown tipova i predlozi semestra iz postojećih fajlova
- [x] Ime fajla `YYYY-MM-DD-slug.md` (events) / slug (blog), provera duplikata
- [x] Draft opcija, izbor slike iz galerije, kategorije/tagovi
- [x] Legacy push tok očuvan (`/save`)

### 4. Izmena aktivnosti
- [x] Po jeziku + sinhronizovano (zajednička polja: date, event_type, image, draft)
- [x] Rename kao posebna operacija (create+delete u sva 3 jezika, isti commit)

### 5. Brisanje
- [x] Soft-delete (draft=true) podrazumevano; trajno brisanje uz dvostruku potvrdu
- [x] Prikaz referenci slika pre brisanja

### 6. Fotografije
- [x] Galerija sa thumbnail-ovima (raw.githubusercontent.com), folderi, „neiskorišćene"
- [x] Upload (jpg/png/webp/gif, max 5 MB, magic-byte validacija), zamena (PUT isti path), brisanje (blokirano ako je referencirana)
- [x] Referentna mapa slika → fajlovi koji je koriste
- [x] Picker u editoru aktivnosti i odboru

### 7. Automatski prevod
- [x] Pluggable provajder (env konfiguracija), nikad u frontendu
- [x] Besplatni provajderi bez ključa: Google Translate endpoint (default) + MyMemory fallback (dnevni besplatni limit ~5000 karaktera)
- [x] Duga tela se dele na chunkove (paragrafi/reči) zbog URL i per-request limita
- [x] Predlog prevoda pre pending-a; „preskoči" i ručni unos po jeziku

### 8. Odbor
- [x] Grid: red=član, kolone jezika za role/university/study; name/email/image zajednički
- [x] Dodavanje/uklanjanje/reorder; sinhroni upis 3 fajla u jednom commitu

### 9. Dokumenta
- [x] CRUD nad `docs[]` u 3 jezika; upload PDF u `static/documents/`; bez URL = „uskoro"

### 10. Postavke
- [x] hugo.toml: samo email/linkedin/instagram/joinFormUrl/brandLogo/ogImage/defaultImage/description (string-level, ostatak netaknut)
- [x] i18n tabelarni editor: komentari i redosled očuvani; validacija identičnih ključeva

### 11. Ostale stranice
- [x] Editori: about (`what[]`, `values[]`), alumni (`highlights[]`), support (`ways[]`), join/contact/media, guide stranice — po jeziku

### 12. SEO i konzistencija
- [x] title/description/image po stranici; globalni parametri u postavkama
- [x] Upozorenje ako se kontakt kanali u `hugo.toml` i `content/contact/_index.md` razlikuju

### Dodatno
- [x] Detekcija neiskorišćenih slika (filter u galeriji)
- [x] Rečnik kategorija/tagova (datalist autocomplete)
- [x] Istorija fajla (commits API) + rollback kao novi commit u pending
- [x] Status poslednjeg deploya (Actions API) na dashboard-u
