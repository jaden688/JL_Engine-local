# ==============================================================================
# DIRTY JULIA AI CHAT SCRIPT
# This script installs its own dependencies, asks for your API key, 
# and gives you an interactive terminal chat with Gemini.
# ==============================================================================

println("Booting up... Checking if we need to install anything...")

# 1. AUTO-INSTALL DEPENDENCIES (No package manager knowledge required!)
import Pkg
# Temporarily mute Pkg output unless it's actually installing
Pkg.add(["HTTP", "JSON3"])

using HTTP
using JSON3

# 2. GET THE API KEY
println("\n" * "="^50)
println("🤖 JULIA NATIVE AI TERMINAL")
println("="^50)
println("Get a free API key here: https://aistudio.google.com/app/apikey\n")
print("Paste your Gemini API Key: ")
api_key = strip(readline())

if isempty(api_key)
    println("Error: You need an API key to talk to the AI. Exiting.")
    exit()
end

# 3. CHAT LOOP
println("\n[Connection Established. Type 'exit' to quit.]")
println("-" ^ 50)

# We keep a history array so the AI remembers the conversation
history = []

while true
    print("\nYou: ")
    user_input = strip(readline())
    
    # Exit condition
    if lowercase(user_input) in ("exit", "quit", "q")
        println("Goodbye!")
        break
    elseif isempty(user_input)
        continue
    end
    
    # Add user message to history
    push!(history, Dict("role" => "user", "parts" => [Dict("text" => user_input)]))
    
    # Prepare the data to send to Google's servers
    payload = Dict("contents" => history)
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=$api_key"
    
    try
        print("Gemini is thinking...")
        
        # Make the web request
        response = HTTP.post(
            url, 
            ["Content-Type" => "application/json"], 
            JSON3.write(payload)
        )
        
        # Clear the "thinking" text
        print("\r" * " "^25 * "\r")
        
        # Parse the JSON response
        res_data = JSON3.read(response.body)
        ai_response_text = res_data.candidates[1].content.parts[1].text
        
        # Print the AI's response
        println("Gemini: \n", strip(ai_response_text))
        
        # Add AI response to history so it remembers for the next turn
        push!(history, Dict("role" => "model", "parts" => [Dict("text" => ai_response_text)]))
        
    catch e
        print("\r" * " "^25 * "\r")
        println("❌ ERROR: Something went wrong. Did you paste a valid API key?")
        println("Error details: ", e)
        pop!(history) # Remove the last message so it doesn't break future turns
    end
end
