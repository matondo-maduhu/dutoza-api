# Hatua ya 4 - Admin Panel mpya

## Faili MPYA
- admin_panel.py                      : Muhtasari, Users, Moderation, Reports, Quotes hub, import ya grid
- guard.py                            : mtumiaji aliyezuiwa anatolewa hata kama alikuwa ameingia
- templates/admin/panel_base.html        : muundo + rangi + sidebar + mode ya giza
- templates/admin/panel_overview.html, panel_users.html, panel_content.html, panel_reports.html, panel_quotes.html, panel_pager.html

## Developers (imeongezwa)
- Kurasa: /admin/developers (orodha) na /admin/developers/<id> (usimamizi wa kila developer)
- templates/admin/panel_developers.html, panel_developer.html (mpya)
- Simamisha/rudisha developer: akisimamishwa keys zake zote zinazimwa na anatolewa kwenye /developers/*
- Kwa kila key: washa, zima, futa (revoke), na badilisha limit ya requests kwa dakika
- schema.py: column developers.status (additive, default 'active'), index api_keys(owner_email)
- guard.py: inalinda pia session za developers
- Keys ulizotengeneza mwenyewe (zisizo na developer) zinabaki kwenye /admin/api-keys

## Usajili wa developer (imebadilishwa)
- developers.py: developer akijisajili HAPEWI API key moja kwa moja tena. Anatengeneza mwenyewe
  kwenye dashboard (Create New API Key). Sehemu nyingine za developers.py hazijabadilika.

## Scopes + maombi ya API keys (idhini ya admin)
- Key sasa ina huduma: Quotes / Muziki / Zote (api_keys.scopes). Keys ZILIZOPO zinapewa "Zote" (DEFAULT),
  kwa hiyo hakuna app ya developer inayovunjika.
- Developer anapotengeneza key anajaza: jina, huduma, matumizi, aina ya mradi, (hiari) website na matumizi
  yanayotarajiwa, na anakubali masharti.
- Quotes pekee = active mara moja. Muziki au Zote = "pending" hadi admin aidhinishe.
  Developer hawezi kuwa na maombi zaidi ya 3 yanayosubiri kwa wakati mmoja.
- Admin: /admin/key-requests (idhinisha na weka limit, au kataa na sababu), na badilisha huduma za key
  kwenye /admin/developers/<id>. Sidebar na Muhtasari zinaonyesha idadi ya maombi.
- auth.py: inakagua scope ya key kulingana na huduma (cache ya sekunde 30, hakuna query ya ziada kila request).
  Kama column ya scopes bado haipo, tabia ya zamani inabaki (keys zinaruhusiwa vyote).
- Faili: auth.py, developers.py, schema.py, admin_panel.py, templates/developers/dashboard.html,
  templates/admin/panel_keyrequests.html (mpya), panel_developer.html, panel_base.html, panel_overview.html

## Mpangilio mpya wa portal ya developers (top nav + bottom nav)
- Simu: juu = brand, avatar (profile) na logout; chini = Dashboard, Keys, Docs, Profile, Settings.
  Desktop: viungo vyote juu (bottom nav inafichwa).
- Kurasa: /developers/dashboard (muhtasari), /developers/keys (tengeneza na simamia keys),
  /developers/profile (jina, kampuni, website, nchi, maelezo), /developers/settings (badilisha password).
- Docs (/developers) inaonyesha bottom nav kwa developer aliyeingia.
- Icons ni SVG za ndani (hazitegemei Font Awesome/CDN).
- schema.py: developers.company, website, country, bio (additive). Profile inafanya kazi hata kabla ya schema.
- Faili: developers.py, schema.py, app.py, templates/developers/{_icons,_bottom_nav,portal_base,dashboard,
  keys,profile,settings,index,register}.html
- Marekebisho: cache ya badge za admin (admin_panel.py) haikuwa sahihi sekunde 20 za kwanza baada ya server kuwaka.

## Docs: Getting Started inayobofya (templates/developers/index.html)
- Hatua 1, 2, 3 sasa zinabofyeka na kufunguka (accordion, moja wazi kwa wakati). Viungo vya moja kwa moja: /developers#step-2.
- Hatua 1: kujisajili, fomu ya key (kila field), lini key inaanza kufanya kazi (Quotes mara moja; Muziki baada ya idhini).
- Hatua 2: header ya Bearer, mifano ya cURL/JavaScript/Python (tabs), kulinda key, makosa 401/403.
- Hatua 3: endpoints zote, query parameters, umbo la jibu, kusoma kurasa zote, rate limit headers na 429.
- Marekebisho ya ukweli: limit ya kawaida ni 100/min (docs ilisema 60); jedwali la makosa lilikosa 403;
  mifano ya curl ya zamani (/api/music, /api/quotes) ilirudisha redirect 308 - sasa ina "/" mwishoni.
- Simu: header ya docs haigongani tena; majedwali ya hatua yanakuwa kadi kwenye simu ndogo.

## Hatua ya 3: UI mpya ya watumiaji wa app
- Bottom nav ya vitu 5: Home, Search, Post (kitufe cha katikati), Alerts (badge), Profile. Top bar: jina, kitufe cha giza/mwanga, avatar.
- Kengele ya notifications sasa inafanya kazi kwenye kurasa ZOTE (hapo awali ilifanya kazi kwenye feed tu).
- Mode ya giza: Auto / Mwanga / Giza (Settings > Mwonekano, au kitufe cha juu). CSS ya giza inazalishwa kutoka CSS yako: `python3 tools/gen_dark.py`
  (endesha tena ukibadilisha rangi kwenye templates).
- PWA: manifest, icons, service worker (hahifadhi kurasa wala API, ni ukurasa wa offline + icons + Font Awesome tu), ukurasa wa /offline, kitufe cha "Sakinisha".
- Mini-player ya muziki: inaonekana wimbo ukiendelea kucheza na kadi yake ikiwa nje ya skrini.
- Skeleton loaders badala ya "Inapakia posts...", na infinite scroll ya feed (inatumia has_more/next_before; ombi la kwanza ni posts 20).
- Faili mpya: pwa.py, static/ (sw.js, icons, css/app-shell.css, css/dark/*, js/app-shell.js), templates/offline.html, tools/gen_dark.py
- Faili zilizobadilika: app.py, templates/users/{base,feed,profile,search,settings,static_page,login,register,public_profile,music_composer}.html
- Kumbuka: icons za app zinatoka Font Awesome (CDN) kama zamani; service worker inazihifadhi ili zifanye kazi offline baada ya ziara ya kwanza.

## Faili ZILIZOBADILIKA
- app.py                              : inasajili panel_bp na guard
- admin.py                            : /admin sasa inaelekeza /admin/overview; add_quote, add_category na
                                        bulk_upload zinarudi kwenye ukurasa ulioombwa (parameter "next")
- schema.py                           : table admin_audit_log, columns za content_reports (status, resolution,
                                        resolved_at), indexes 4 mpya - zote additive (IF NOT EXISTS)
- templates/admin/schema_status.html  : muonekano mpya + ukaguzi wa columns

## Kurasa mpya
/admin/overview   /admin/quotes   /admin/content   /admin/reports   /admin/users

## Hayajafutwa
Music admin (/admin/music), API keys (/admin/api-keys), bulk-upload ya zamani (/admin/quotes/bulk-upload)
zinaendelea kufanya kazi kama zamani. Hakuna table wala column iliyofutwa.

## Kurudi nyuma
Rudisha app.py, admin.py, schema.py na schema_status.html za awali; futa admin_panel.py, guard.py na faili za panel_*.html
templates/admin/panel. Columns/tables mpya hazidhuru.
