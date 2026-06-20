// Load .env before any other import: route/controller construction reads
// process.env at import time, so dotenv must run first.
import "dotenv/config";
import express from "express";
import path from "path";
import cors from "cors";
import helmet from "helmet";
import morgan from "morgan";
import analysisRoutes from "./routes/analysis.routes";

const app = express();
const port = parseInt(process.env.PORT || "3000", 10);

// CSP disabled: the frontend is a single self-contained page with an inline
// <script>/<style>, which helmet's default `script-src 'self'` would block.
app.use(helmet({ contentSecurityPolicy: false }));
app.use(cors());
app.use(morgan("dev"));
app.use(express.json());

app.use("/api/analysis", analysisRoutes);

app.get("/health", (_req, res) => {
  res.json({ status: "ok", timestamp: new Date().toISOString() });
});

app.use(express.static(path.join(__dirname, "../frontend")));

app.listen(port, () => {
  console.log(`[Server] Running on http://localhost:${port}`);
  console.log(`[Server] Frontend at http://localhost:${port}`);
  console.log(`[Server] API at http://localhost:${port}/api/analysis`);
});

export default app;
