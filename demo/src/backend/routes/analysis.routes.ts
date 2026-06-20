import { Router, Request, Response } from "express";
import { AnalysisController } from "../controllers/analysis.controller";

const router = Router();
const controller = new AnalysisController();

router.post("/analyze", (req: Request, res: Response) => controller.analyzeStock(req, res));
router.get("/integrations", (req: Request, res: Response) => controller.getIntegrationsStatus(req, res));

export default router;
