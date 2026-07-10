use notes_showcase::{run_interactive, run_smoke};

fn main() -> Result<(), Box<dyn std::error::Error>> {
    if std::env::args().any(|arg| arg == "--smoke") {
        println!("{}", run_smoke()?);
        return Ok(());
    }
    run_interactive()?;
    Ok(())
}
