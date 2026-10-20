function mandelbrot(a)
    z = complex(0.0, 0.0)
    for i=1:50
        z = z^2 + a
        abs(z) > 2 && return false
    end
    return true
end

println("Here is a Mandelbrot set generated in Julia!")
println("-" ^ 50)

for y = -1.0:0.07:1.0
    for x = -2.0:0.04:0.5
        if mandelbrot(complex(x,y))
            print("█")
        else
            print(" ")
        end
    end
    println()
end
