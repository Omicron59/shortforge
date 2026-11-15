import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, eventsUrl } from "../api/client";

afterEach(() => vi.unstubAllGlobals());

function reply(status: number, body: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));
}

describe("client API", () => {
  it("pointe par defaut sur le backend local 8787", () => {
    expect(eventsUrl("p1")).toBe("ws://127.0.0.1:8787/api/projects/p1/events");
  });
  it("renvoie le message d'erreur francais du backend", async () => {
    reply(409, { detail: "« Choix de l'idée » attend ta validation." });
    await expect(api.advance("p1")).rejects.toThrow("attend ta validation");
  });
  it("resume les erreurs de validation", async () => {
    reply(422, { detail: [{ loc: ["body", "x"] }] });
    await expect(api.setBudget({ budget_max_per_day: -1 })).rejects.toThrow("Valeur refusée");
  });
  it("signale un backend injoignable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const error = await api.health().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).message).toContain("injoignable");
  });
  it("envoie la confirmation de depense explicitement", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await api.approve("p1", "generate_videos", true);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/projects/p1/steps/generate_videos/approve");
    expect(JSON.parse(String(init.body))).toEqual({ validated_by: "utilisateur", confirm: true });
  });
});
