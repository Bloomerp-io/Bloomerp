import assert from "node:assert/strict";
import test from "node:test";
import { BloomerpHttpClient } from "./sdk.ts";

/** Verify browser multipart boundaries survive SDK session authentication. */
async function verifyMultipartRequest(): Promise<void> {
    let received: Request | null = null;
    /** Capture the wire request without contacting a server. */
    async function capture(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
        received = new Request(input, init);
        return Response.json({ draft_id: "saved" });
    }
    const client = new BloomerpHttpClient({
        baseUrl: "https://example.test", fetch: capture,
        auth: { type: "session", csrf: { token: "test-csrf" } },
    });
    const body = new FormData();
    body.set("body", "Edited email");
    body.set("attachments", new Blob(["draft file"], { type: "text/plain" }), "note.txt");
    assert.deepEqual(await client.request("/draft", { method: "POST", body }), { draft_id: "saved" });
    assert.match(received!.headers.get("Content-Type")!, /^multipart\/form-data; boundary=/);
    assert.equal(received!.headers.get("X-CSRFToken"), "test-csrf");
    const parsed = await received!.formData();
    assert.equal(parsed.get("body"), "Edited email");
    assert.equal(await (parsed.get("attachments") as File).text(), "draft file");
}

/** Verify model API JSON calls retain their existing content-type behavior. */
async function verifyJsonRequest(): Promise<void> {
    /** Inspect serialized JSON at the transport boundary. */
    async function capture(input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
        const request = new Request(input, init);
        assert.equal(request.headers.get("Content-Type"), "application/json");
        assert.deepEqual(await request.json(), { title: "Example" });
        return Response.json({ id: 1 });
    }
    const client = new BloomerpHttpClient({ baseUrl: "https://example.test", fetch: capture });
    await client.request("/api/todos", { method: "POST", body: JSON.stringify({ title: "Example" }) });
}

test("SDK preserves multipart fields, file bytes, and CSRF", verifyMultipartRequest);
test("SDK continues to label serialized model payloads as JSON", verifyJsonRequest);
