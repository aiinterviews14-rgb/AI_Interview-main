import requests

def test_tts():
    text = "Identity Verified. Now, let's calibrate your environment."
    url = f"http://localhost:5000/api/tts?text={requests.utils.quote(text)}"
    print(f"Calling: {url}")
    try:
        response = requests.get(url)
        print(f"Status Code: {response.status_code}")
        if response.status_code == 200:
            print(f"Success! Content length: {len(response.content)}")
            with open("test_voice.wav", "wb") as f:
                f.write(response.content)
            print("Audio saved to test_voice.wav")
        else:
            print(f"Error Body: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_tts()
