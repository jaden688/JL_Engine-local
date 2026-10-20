# gemini_assistant.jl
# A simple helper script to interact with Gemini CLI from within Julia

module GeminiAssistant

export ask_gemini

function ask_gemini(prompt::String)
    println("Asking Gemini: ", prompt)
    println("-" ^ 40)
    
    try
        # On Windows, npm creates a .cmd wrapper for global CLIs
        # We use cmd /c to ensure it resolves the command correctly
        run(`cmd /c gemini --version`)
    catch e
        println("Error calling Gemini CLI from Julia: ", e)
    end
end

end

using .GeminiAssistant
GeminiAssistant.ask_gemini("Hello from Julia!")
