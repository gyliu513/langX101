
# Running scira-mcp-chat Locally

If you’d like to run **scira‑mcp‑chat** locally (the next.js‑based Model Context Protocol client by zaidmukaddam), here’s how to do it based on the official README and configuration files.

---

## Steps to Run Locally

### 1. Clone the Repository
```bash
git clone https://github.com/zaidmukaddam/scira-mcp-chat.git
cd scira-mcp-chat
```
This project is a Next.js app with AI tools powered by Vercel’s AI SDK and support for MCP servers.

### 2. Copy Environment Configuration
Duplicate the `.env.example` file and fill in your credentials:
```bash
cp .env.example .env.local
```
Set at least:
- `XAI_API_KEY`
- `OPENAI_API_KEY`

Optionally, if the app supports a database backend, you can also configure `DATABASE_URL`.

### 3. Install Dependencies
The project uses `pnpm`, so run:
```bash
pnpm install
```

### 4. Start the Development Server
Once dependencies are installed:
```bash
pnpm dev
```
This launches the app with TurboPack on your local environment.

### 5. Visit in Your Browser
Navigate to [http://localhost:3000](http://localhost:3000) to access the UI.

---

## Configuring MCP Servers
Within the UI, click the **settings icon (⚙️)** next to the model selector to add an MCP server:

- **SSE transport**: Enter the server’s SSE URL (e.g. `https://mcp.example.com/token/sse`).
- **stdio transport**: Provide the execution command (e.g. `npx`) and any arguments like `-y @modelcontextprotocol/server-google-maps`. You can enter space-separated arguments or a JSON array.

Click **Add Server**, then **Use** to activate for the session.

You can connect to any MCP‑compatible server, such as Composio, Zapier MCP, or others supporting your chosen transport method.

---

## Summary Table

| Step               | Command / Action                                   |
|--------------------|----------------------------------------------------|
| Clone repo         | `git clone … && cd scira-mcp-chat`                |
| Setup env vars     | `cp .env.example .env.local` → fill in API keys   |
| Install deps       | `pnpm install`                                    |
| Run dev server     | `pnpm dev`                                        |
| Open in browser    | Go to `http://localhost:3000`                     |
| Add MCP server     | Use UI’s settings (⚙️) → configure transport + URL or cmd |

---

