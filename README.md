# Robaws MCP Server — Instructies voor Claude Code

## Context & Doel

We willen dat Claude AI (via de Claude.ai desktop app) rechtstreeks toegang krijgt tot onze Robaws data, zodat hij live vragen kan beantwoorden en analyses kan doen. Dit gebeurt via een **MCP server** (Model Context Protocol) — hetzelfde protocol waarmee Claude toegang heeft tot tools zoals browsers en Gmail.

De server draait op **Railway** (cloud, 24/7 beschikbaar) en communiceert via HTTP met de Claude desktop app. Alle Robaws data blijft intern — de server doet enkel read-only calls naar de Robaws API.

---

## Robaws API

- **Base URL:** `https://app.robaws.com/api/v2`
- **API Documentatie:** `https://app.robaws.com/public/api-docs/robaws`
- **Authenticatie:** HTTP Basic Auth met API key en secret (zie voorbeeld script)
- **API Key:** [INVULLEN — sla op als Railway environment variable, NOOIT hardcoded in de code]
- **API Secret:** [INVULLEN — sla op als Railway environment variable]

> **Tip:** Gebruik het bestaande foto-download script als referentie voor de auth configuratie. Die connectie werkt al.

De API gebruikt **paginatie** (`page` en `size` parameters) en geeft JSON terug.

---

## Wat de MCP server moet doen

De server stelt Claude in staat om via gestructureerde tools Robaws data op te vragen.

### Veiligheidsregel: enkel read-only

**Alleen GET requests.** Geen POST, PUT, PATCH of DELETE. Dit is een harde eis.

### Te implementeren tools (minimum)

Implementeer minstens de volgende tools, elk als aparte MCP tool met een duidelijke Engelstalige beschrijving zodat Claude weet wanneer hij welke aanroept:

| Tool naam | Omschrijving |
|---|---|
| `get_work_orders` | Werkbonnen ophalen (filters: status, datum, klant) |
| `get_clients` | Klanten ophalen (filter: zoekterm, naam) |
| `get_projects` | Projecten ophalen (filters: status, fase) |
| `get_offers` | Offertes ophalen |
| `get_invoices` | Verkoopfacturen ophalen (sales invoices) |
| `get_purchase_orders` | Inkooporders ophalen |
| `get_purchase_invoices` | Inkoopfacturen ophalen |
| `get_employees` | Medewerkers ophalen |
| `get_planning` | Planning items ophalen (dag planning) |
| `get_articles` | Artikelen/producten ophalen |
| `get_suppliers` | Leveranciers ophalen |
| `get_stock_locations` | Voorraadlocaties ophalen |
| `get_tasks` | Taken ophalen |
| `search_robaws` | Generieke tool: accepteert een endpoint path + query params, voor alles buiten bovenstaande tools |

### Parameters per tool

Elke tool ondersteunt minstens:
- `size` (default: 25, max: 100)
- `page` (voor paginatie, default: 0)
- Entiteit-specifieke filters waar relevant (bv. `status`, `date_from`, `date_to`, `client_id`)

### Foutafhandeling

- Geef zinvolle foutmeldingen terug als de API niet bereikbaar is of een fout geeft
- Log errors maar gooi geen crashes die de MCP server doen stoppen

---

## Technische eisen

### Stack (voorkeur Python + FastMCP)

Gebruik **FastMCP** — dit is de officiële high-level Python library bovenop de MCP SDK, specifiek gebouwd voor remote servers op cloud platforms zoals Railway.

```
pip install fastmcp httpx python-dotenv
```

### Transport: Streamable HTTP

Voor Railway gebruik je **Streamable HTTP transport** (niet `stdio` zoals bij lokale servers). Dit is de moderne standaard voor remote MCP servers:

```python
# server.py
from fastmcp import FastMCP
import httpx

mcp = FastMCP("Robaws Assistant")

@mcp.tool()
async def get_work_orders(limit: int = 25, page: int = 0, status: str = None) -> dict:
    """Fetch work orders from Robaws. Optionally filter by status."""
    # ... implementatie

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

### Configuratie via environment variables

```
ROBAWS_API_KEY        = jouw-robaws-api-key
ROBAWS_API_SECRET     = jouw-robaws-api-secret
ROBAWS_BASE_URL       = https://app.robaws.com/api/v2
MCP_AUTH_TOKEN        = zelf-gekozen-geheim-token-voor-beveiliging
PORT                  = 8000
```

> **`MCP_AUTH_TOKEN`**: Dit is een token dat jij zelf kiest en instelt, zodat niet iedereen met de publieke Railway URL jouw MCP server kan aanroepen. Je voegt het toe als `Authorization: Bearer <token>` header bij het verbinden vanuit Claude Desktop.

### Bestandsstructuur

```
robaws-mcp/
├── server.py            # MCP server hoofdbestand (FastMCP)
├── robaws_client.py     # HTTP client voor Robaws API calls
├── requirements.txt     # Python dependencies
├── Dockerfile           # Voor Railway deployment
├── railway.toml         # Railway configuratie
├── .env.example         # Voorbeeld env file (GEEN echte keys)
└── README.md            # Installatie instructies
```

### requirements.txt

```
fastmcp>=2.0.0
httpx>=0.27.0
python-dotenv>=1.0.0
```

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["python", "server.py"]
```

### railway.toml

```toml
[build]
builder = "dockerfile"

[deploy]
startCommand = "python server.py"
healthcheckPath = "/health"
restartPolicyType = "on-failure"
```

---

## Deployment op Railway

### Stap 1 — Railway project aanmaken

1. Ga naar [railway.com](https://railway.com) en log in
2. Klik **New Project** → **Deploy from GitHub repo**
3. Verbind je GitHub account en selecteer de repository van deze server
4. Railway detecteert automatisch de Dockerfile en start de build

### Stap 2 — Environment variables instellen

In Railway, ga naar je service → **Variables** tab → voeg toe:

```
ROBAWS_API_KEY        = jouw-robaws-api-key
ROBAWS_API_SECRET     = jouw-robaws-api-secret
ROBAWS_BASE_URL       = https://app.robaws.com/api/v2
MCP_AUTH_TOKEN        = kies-een-sterk-willekeurig-token
PORT                  = 8000
```

### Stap 3 — Publieke URL activeren

1. Ga naar je service → **Settings** → **Networking**
2. Klik **Generate Domain**
3. Railway geeft je een URL zoals `https://robaws-mcp-production.up.railway.app`

Dit is de URL die je in Claude Desktop configureert.

### Stap 4 — Verbinden met Claude Desktop

Voeg dit toe aan de Claude Desktop config:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "robaws": {
      "type": "http",
      "url": "https://robaws-mcp-production.up.railway.app/mcp",
      "headers": {
        "Authorization": "Bearer jouw-MCP_AUTH_TOKEN-hier"
      }
    }
  }
}
```

> Vervang de URL met jouw echte Railway domain, en de Bearer token met het `MCP_AUTH_TOKEN` dat je in Railway hebt ingesteld.

Na het aanpassen: **Claude Desktop volledig afsluiten en opnieuw opstarten.**

---

## Beveiliging — samenvatting

| Maatregel | Waarom |
|---|---|
| `MCP_AUTH_TOKEN` header | Voorkomt dat iemand anders jouw Railway URL kan aanroepen |
| Enkel GET requests in de server | Claude kan nooit per ongeluk data wijzigen of verwijderen |
| API key als Railway env variable | Nooit zichtbaar in code of logs |
| Read-only Robaws API key (indien mogelijk) | Extra laag: zelfs als de key lekt, kan er niets geschreven worden |

---

## Verificatie

Test de server door deze vragen aan Claude te stellen na het instellen:
- "Geef me de laatste 10 werkbonnen"
- "Hoeveel open offertes hebben we?"
- "Welke projecten zijn momenteel actief?"
- "Zoek klant [naam]"

Als Claude deze vragen kan beantwoorden met live data, werkt alles correct.

---

## Referentie

Het bestaande Python script dat foto's downloadt via de Robaws API bevat de werkende auth configuratie. Gebruik dat als startpunt voor `robaws_client.py`.

De volledige API documentatie (endpoints, parameters, response schemas) staat op:
`https://app.robaws.com/public/api-docs/robaws`

---

## Tijdsinschatting

| Fase | Geschatte tijd |
|---|---|
| Server schrijven, auth testen, eerste tool werkend | ~30 min |
| Alle 10 tools implementeren met filters | ~1–2 uur |
| Dockerfile + Railway deployment | ~30 min |
| Claude Desktop configureren + testen | ~15 min |
| **Totaal** | **2–3 uur** |
