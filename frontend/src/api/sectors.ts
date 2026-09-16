// Sector rules for demo mode. Mirror of backend/app/services/sectors.py: keep both in sync.
import type { SectorMatch } from "./types";

interface Rule {
  key: string;
  label: string;
  nace: string[];
  words: string[];
}

export const SECTOR_RULES: Rule[] = [
  { key: "bakkerij", label: "Bakkerijen & banket", nace: ["1071", "1072", "4724"],
    words: ["bakker\\w*", "boulanger\\w*", "patisserie\\w*", "patissier\\w*", "banket\\w*", "brood(?!je)\\w*", "viennoiserie\\w*", "chocolat\\w*"] },
  { key: "horeca", label: "Horeca", nace: ["55", "56"],
    words: ["restaurant\\w*", "frituur\\w*", "friture\\w*", "cafe\\w*", "brasserie\\w*", "bistro\\w*", "pizzeria\\w*", "pizza\\w*",
      "snack\\w*", "broodje\\w*", "eethuis", "taverne", "traiteur\\w*", "sushi", "kebab\\w*", "grill\\w*", "hotel\\w*", "catering\\w*", "bar"] },
  { key: "zorg", label: "Zorg & welzijn", nace: ["86", "87", "88", "4773", "4774"],
    words: ["apothe\\w*", "kinesi\\w*", "tandarts\\w*", "dental\\w*", "dokter\\w*", "huisarts\\w*", "medisch\\w*", "medical\\w*",
      "verpleeg\\w*", "thuiszorg\\w*", "zorg\\w*", "hoorcentrum\\w*", "optiek\\w*", "opticien\\w*", "psycholo\\w*", "logopedi\\w*",
      "fysio\\w*", "moveo"] },
  { key: "kapper", label: "Kappers & schoonheid", nace: ["9602", "9604"],
    words: ["kapper\\w*", "kapsalon\\w*", "coiff\\w*", "hair\\w*", "kapsel\\w*", "schoonheid\\w*", "beauty\\w*", "nagel\\w*",
      "nails?", "barber\\w*", "wellness\\w*"] },
  { key: "bouw", label: "Bouw & installatie", nace: ["41", "42", "43"],
    words: ["bouw\\w*", "renovat\\w*", "dakwerk\\w*", "schilder\\w*", "elektri\\w*", "loodgiet\\w*", "sanitair\\w*", "installat\\w*",
      "tegel\\w*", "aannem\\w*", "schrijnwerk\\w*", "verwarming\\w*"] },
  { key: "auto", label: "Auto & mobiliteit", nace: ["45", "4932", "8553"],
    words: ["garage\\w*", "autobedrijf\\w*", "autohandel\\w*", "autoservice\\w*", "car", "carrosser\\w*", "banden\\w*",
      "rijschool\\w*", "taxi\\w*", "fiets\\w*"] },
  { key: "winkel", label: "Winkels & detailhandel", nace: ["47"],
    words: ["winkel\\w*", "shop\\w*", "boetiek\\w*", "boutique\\w*", "bloem(?:en|ist|isterij|enwinkel|enzaak|enhandel)",
      "slager\\w*", "beenhouwer\\w*", "juwel\\w*", "mode", "supermarkt\\w*", "kruidenier\\w*", "store"] },
  { key: "advies", label: "Advies & vrije beroepen", nace: ["69", "70", "71", "6622"],
    words: ["boekhoud\\w*", "accountan\\w*", "advocat\\w*", "notaris\\w*", "fiscal\\w*", "consult\\w*", "verzekering\\w*",
      "architect\\w*", "taxcal\\w*", "tax"] },
];

const PATTERNS = SECTOR_RULES.map((r) => new RegExp(`\\b(?:${r.words.join("|")})\\b`));

const normalize = (s: string) => s.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function classifySectors(record: {
  names: Array<string | null | undefined>;
  legalForm: string | null;
  naceCode?: string | null;
  naceDescription?: string | null;
}): SectorMatch[] {
  const coOwnership = normalize(`${record.legalForm ?? ""} ${record.names.join(" ")}`);
  if (coOwnership.includes("mede-eigenaars") || coOwnership.includes("mede eigenaars")) return [];
  const names = normalize(record.names.filter(Boolean).join(" | "));
  const digits = (record.naceCode ?? "").replace(/\D/g, "");
  const matches: SectorMatch[] = [];
  SECTOR_RULES.forEach((rule, i) => {
    let reason: string | null = null;
    if (digits && rule.nace.some((p) => digits.startsWith(p))) {
      reason = `activiteitscode ${record.naceCode}${record.naceDescription ? ` (${record.naceDescription})` : ""}`;
    } else {
      const hit = PATTERNS[i].exec(names);
      if (hit) reason = `naam bevat "${hit[0]}"`;
    }
    if (reason) matches.push({ value: rule.key, label: rule.label, reason });
  });
  return matches;
}
