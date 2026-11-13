# 0001: Static site without an application server

The published site will be built from collected and assessed data as static JSON and assets, then served on GitHub Pages. Scheduled workflows collect weather, refresh launch data and build the site; the browser does not need an application server to run assessments. This keeps hosting and operation simple, but the displayed forecasts depend on the last successful collection and must expose their freshness and any deferred refresh.
