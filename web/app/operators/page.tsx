import Nav from "@/components/Nav";
import Agents from "@/components/Agents";
import Footer from "@/components/Footer";

export default function OperatorsPage() {
  return (
    <>
      <Nav />
      <main className="pt-16">
        <Agents />
      </main>
      <Footer />
    </>
  );
}
