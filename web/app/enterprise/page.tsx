import Nav from "@/components/Nav";
import Enterprise from "@/components/Enterprise";
import Footer from "@/components/Footer";

export default function EnterprisePage() {
  return (
    <>
      <Nav />
      <main className="pt-16">
        <Enterprise />
      </main>
      <Footer />
    </>
  );
}
