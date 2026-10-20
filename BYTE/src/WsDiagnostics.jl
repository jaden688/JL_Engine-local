# Static coverage follows actual send arguments and payload helper returns.
# Nested node/schema dictionaries are never treated as message envelopes.
function _ws_emitted_types(sources::Vector{String})
    trees = Meta.parseall.(sources)
    functions = Dict{Symbol,Any}()
    name(x) = x isa Symbol ? x : x isa Expr && x.head == :curly ? name(x.args[1]) :
        x isa Expr && x.head == :. ? name(x.args[end]) :
        x isa QuoteNode ? name(x.value) : nothing
    function walk(f, x)
        x isa Expr || return
        f(x)
        foreach(a -> walk(f, a), x.args)
    end
    function definition(x)
        if x.head == :function
            sig = x.args[1]
            sig isa Expr && sig.head == :where && (sig = sig.args[1])
            sig isa Expr && sig.head == :call && return (name(sig.args[1]), x.args[2])
        elseif x.head == :(=) && x.args[1] isa Expr && x.args[1].head == :call
            return (name(x.args[1].args[1]), x.args[2])
        end
        return (nothing, nothing)
    end
    for tree in trees
        walk(tree) do x
            n, body = definition(x)
            n === nothing || (functions[n] = body)
        end
    end
    function bindings(body)
        env = Dict{Symbol,Vector{Any}}()
        walk(body) do x
            if x.head == :(=) && x.args[1] isa Symbol
                push!(get!(env, x.args[1], Any[]), x.args[2])
            end
        end
        env
    end
    function resolve(x, env, seen=Set{Any}())
        result = Set{String}()
        if x isa Symbol
            x in seen && return result
            for value in get(env, x, Any[])
                union!(result, resolve(value, env, union(seen, Set([x]))))
            end
        elseif x isa Expr && x.head == :call
            n = name(x.args[1])
            if n == :Dict
                for pair in x.args[2:end]
                    if pair isa Expr && pair.head == :call && pair.args[1] == :(=>) &&
                       pair.args[2] == "type" && pair.args[3] isa String
                        push!(result, pair.args[3])
                    end
                end
            elseif n == :json
                length(x.args) > 1 && union!(result, resolve(x.args[2], env, seen))
            elseif haskey(functions, n) && !((:function, n) in seen)
                body = functions[n]
                localenv = bindings(body)
                nextseen = union(seen, Set([(:function, n)]))
                walk(body) do expr
                    expr.head == :return && !isempty(expr.args) &&
                        union!(result, resolve(expr.args[1], localenv, nextseen))
                end
                if body isa Expr && body.head == :block
                    expressions = filter(a -> !(a isa LineNumberNode), body.args)
                    isempty(expressions) || union!(result, resolve(last(expressions), localenv, nextseen))
                else
                    union!(result, resolve(body, localenv, nextseen))
                end
            end
        elseif x isa Expr && x.head in (:return, :if, :block)
            for arg in x.args
                union!(result, resolve(arg, env, seen))
            end
        end
        result
    end
    emitted = Set{String}()
    # Each function has its own variable bindings; same-named locals do not leak.
    for body in values(functions)
        env = bindings(body)
        walk(body) do x
            if x.head == :call
                n = name(x.args[1])
                if n == :_ws_send && length(x.args) >= 3
                    union!(emitted, resolve(x.args[3], env))
                elseif n == :_broadcast && length(x.args) >= 2
                    union!(emitted, resolve(x.args[2], env))
                end
            end
        end
    end
    return emitted
end

