import SQLite, DataFrames, DBInterface, Dates, JSON, Statistics
function query_db(db::SQLite.DB, sql::String, params=())
    isempty(params) ?
        DBInterface.execute(db, sql) |> DataFrames.DataFrame :
        DBInterface.execute(db, sql, params) |> DataFrames.DataFrame
end

println("hello")