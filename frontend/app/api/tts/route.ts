import { NextResponse } from "next/server";
import * as googleTTS from "google-tts-api";

export async function POST(req: Request) {
  try {
    const { text } = await req.json();

    if (!text || text.trim().length === 0) {
      return NextResponse.json(
        { error: "Text is required and cannot be empty" },
        { status: 400 }
      );
    }

    console.log("🔊 Proxying TTS request to Masculine Backend:", text.slice(0, 50), "...");

    // Call the hardened Flask backend which prioritizes Male voices (pyttsx3/edge-tts)
    // Use NEXT_PUBLIC_API_URL or fallback to backend service in Docker, or localhost for local
    const internalBackendUrl = process.env.INTERNAL_BACKEND_URL || process.env.NEXT_PUBLIC_API_URL || "http://backend:5000";
    const backendUrl = `${internalBackendUrl}/api/tts?text=${encodeURIComponent(text)}`;
    const response = await fetch(backendUrl);

    if (!response.ok) {
      throw new Error(`Backend TTS failed: ${response.statusText}`);
    }

    const audioBuffer = await response.arrayBuffer();

    return new Response(audioBuffer, {
      headers: {
        "Content-Type": "audio/mpeg",
      },
    });
  } catch (error: any) {
    console.error("❌ High-Identity TTS Error:", error);
    
    return NextResponse.json(
      { 
        error: "Failed to generate speech", 
        details: error.message || "Internal server error" 
      },
      { status: 500 }
    );
  }
}
