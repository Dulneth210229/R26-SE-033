# Setup Instructions

## Run the app

This project is a working Next.js (App Router + TypeScript) app scaffolded from the start -- these commands work for every feature, not just this one.

```bash
npm install
cp .env.example .env.local   # first time only -- fill in real values
npm run build && npm start   # production build + boot (port 3000)
# or, for local development:
npm run dev                  # boots the Next.js dev server (port 3000)
```

## Required environment variables (add to `server/.env`)

- `MONGODB_URI`
